import os
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.database import engine, get_db, Base
from app import models
from app.schemas import (
    UserCreate, UserResponse, LoginRequest, Token,
    ThreadCreate, ThreadResponse,
    MessageCreate, MessageResponse,
    ChatRequest,
)
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.llm import generate_reply, generate_title, LLMError, ALLOWED_MODELS

# Create tables on startup — for production use Alembic migrations instead
Base.metadata.create_all(bind=engine)

app = FastAPI(title="dboss-backend")

_DEFAULT_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]
_cors_env = os.environ.get("CORS_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _cors_env.split(",") if o.strip()] or _DEFAULT_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@app.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = models.User(
        username=payload.username,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    token = create_access_token({"sub": user.username})
    return Token(access_token=token, token_type="bearer")


@app.get("/me", response_model=UserResponse)
def me(current_user: models.User = Depends(get_current_user)):
    return current_user


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

_MODEL_LABELS = {
    "openai/gpt-oss-120b": "GPT-OSS 120B (Güçlü)",
    "openai/gpt-oss-20b": "GPT-OSS 20B (Hızlı)",
    "qwen/qwen3.6-27b": "Qwen 3.6 27B (Akıllı)",
}


@app.get("/models")
def list_models():
    return [{"id": m, "label": _MODEL_LABELS[m]} for m in ALLOWED_MODELS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_thread_or_404(thread_id: int, current_user: models.User, db: Session) -> models.Thread:
    thread = (
        db.query(models.Thread)
        .filter(models.Thread.id == thread_id, models.Thread.user_id == current_user.id)
        .first()
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------

@app.post("/threads", response_model=ThreadResponse, status_code=status.HTTP_201_CREATED)
def create_thread(
    payload: ThreadCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    thread = models.Thread(user_id=current_user.id, title=payload.title)
    db.add(thread)
    db.commit()
    db.refresh(thread)
    return thread


@app.get("/threads", response_model=list[ThreadResponse])
def list_threads(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Thread)
        .filter(models.Thread.user_id == current_user.id)
        .order_by(models.Thread.updated_at.desc())
        .all()
    )


@app.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    thread = _get_thread_or_404(thread_id, current_user, db)
    db.delete(thread)
    db.commit()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@app.get("/threads/{thread_id}/messages", response_model=list[MessageResponse])
def list_messages(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _get_thread_or_404(thread_id, current_user, db)
    return (
        db.query(models.Message)
        .filter(models.Message.thread_id == thread_id)
        .order_by(models.Message.created_at.asc())
        .all()
    )


@app.post("/threads/{thread_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def create_message(
    thread_id: int,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    thread = _get_thread_or_404(thread_id, current_user, db)
    message = models.Message(
        thread_id=thread_id,
        role=payload.role,
        content=payload.content,
        model=payload.model,
        message_metadata=payload.message_metadata,
    )
    db.add(message)
    # onupdate only fires when Thread's own columns change; adding a message
    # doesn't touch the threads row, so we set updated_at explicitly.
    thread.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(message)
    return message


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@app.post("/threads/{thread_id}/chat", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
def chat(
    thread_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    thread = _get_thread_or_404(thread_id, current_user, db)

    user_msg = models.Message(thread_id=thread_id, role="user", content=payload.content)
    db.add(user_msg)
    db.flush()  # assigns ID without committing; visible within this session

    all_msgs = (
        db.query(models.Message)
        .filter(models.Message.thread_id == thread_id)
        .order_by(models.Message.created_at.asc())
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in all_msgs]

    try:
        reply = generate_reply(history, payload.model)
    except LLMError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}")

    assistant_msg = models.Message(
        thread_id=thread_id,
        role="assistant",
        content=reply["content"],
        model=reply["model"],
        message_metadata=reply["metadata"],
    )
    db.add(assistant_msg)

    if thread.title is None:
        new_title = generate_title(history[0]["content"])
        if new_title and new_title.strip():
            thread.title = new_title.strip()

    thread.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(assistant_msg)
    return assistant_msg
