# backend/app.py
import os
import json
import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

# ========================
#  Настройки окружения
# ========================
YANDEX_API_KEY = os.environ.get("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.environ.get("YANDEX_FOLDER_ID", "")
VECTOR_STORE_ID = os.environ.get("VECTOR_STORE_ID", "")
YANDEX_API_URL = "https://rest-assistant.api.cloud.yandex.net/v1"
YANDEX_LLM_URL = "https://llm.api.cloud.yandex.net/v1/chat/completions"

# Разрешённые домены для CORS
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",")]

# ========================
#  Инициализация FastAPI
# ========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ========================
#  Утилиты
# ========================
def ask_with_context(question: str) -> str:
    """
    Простой запрос напрямую в YandexGPT без vector store (fallback).
    """
    payload = {
        "model": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
        "messages": [
            {"role": "system", "content": "Ты — AI-помощник сайта usadba4.ru"},
            {"role": "user", "content": question},
        ],
        "temperature": 0.0,
        "max_tokens": 500,
    }

    headers = {
        "Authorization": f"Bearer {YANDEX_API_KEY}",
        "OpenAI-Project": YANDEX_FOLDER_ID,
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(YANDEX_LLM_URL, headers=headers, json=payload, timeout=30)
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        print("ask_with_context ERROR:", e)
        return "Извините, сейчас не могу ответить."


def rag_via_responses(question: str) -> str:
    """
    Запрос в YandexGPT с подключением Vector Store через Responses API.
    """
    payload = {
        "model": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt/latest",
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Ты — помощник сайта usadba4.ru. Отвечай строго по базе знаний (Vector Store). "
                                "Если факт не найден — напиши: 'Нет данных в базе знаний'."
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": question}],
            },
        ],
        "tools": [{"type": "file_search"}],
        "tool_resources": {
            "file_search": {"vector_store_ids": [VECTOR_STORE_ID]},
        },
        "temperature": 0.0,
        "max_output_tokens": 600,
    }

    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "x-folder-id": YANDEX_FOLDER_ID,
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(f"{YANDEX_API_URL}/responses", headers=headers, json=payload, timeout=40)
        data = r.json()

        # Прямой ответ
        if "output_text" in data:
            return data["output_text"]

        # Разбор блоков
        texts = []
        for block in data.get("output", []):
            for content in block.get("content", []):
                if content.get("type") == "output_text":
                    texts.append(content.get("text", ""))
        return "\n".join(texts) if texts else "Нет данных в базе знаний."
    except Exception as e:
        print("rag_via_responses ERROR:", e)
        return "Извините, сейчас не могу ответить."


# ========================
#  Роуты
# ========================
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/chat")
def chat_get(q: str = ""):
    q = (q or "").strip() or "Есть ли в усадьбе ресторан?"
    try:
        try:
            ans = rag_via_responses(q)
        except Exception as e:
            print("RAG error (GET):", e)
            ans = ask_with_context(q)
        return {"answer": ans}
    except Exception as e:
        print("FATAL (GET):", e)
        return {"answer": "Извините, сейчас не могу ответить."}


@app.post("/api/chat")
async def chat_post(request: Request):
    try:
        # Читаем JSON безопасно
        try:
            data = await request.json()
        except Exception:
            raw = await request.body()
            data = json.loads(raw.decode("utf-8", errors="ignore") or "{}")

        q = (data.get("question") or "").strip() if isinstance(data, dict) else ""
        if not q:
            q = "Есть ли в усадьбе ресторан?"

        try:
            ans = rag_via_responses(q)
        except Exception as e:
            print("RAG error (POST):", e)
            ans = ask_with_context(q)
        return {"answer": ans}

    except Exception as e:
        print("FATAL (POST):", e)
        return {"answer": "Извините, сейчас не могу ответить."}

