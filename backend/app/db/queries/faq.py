from __future__ import annotations

import asyncpg


async def search_faq(
    pool: asyncpg.Pool, *, query: str, limit: int = 5, min_similarity: float = 0.35
) -> list[dict]:
    sql = """
        SELECT question, answer, similarity(question, $1) AS similarity
        FROM u4s_chatbot.faq
        WHERE question % $1
        ORDER BY similarity(question, $1) DESC
        LIMIT $2
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, query, limit)

    result: list[dict] = []
    for row in rows:
        row_dict = dict(row)
        if (row_dict.get("similarity") or 0.0) >= min_similarity:
            result.append(row_dict)
    return result


__all__ = ["search_faq"]
