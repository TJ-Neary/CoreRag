"""Dashboard chat route — LLM with optional RAG context."""

import logging
import warnings

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)


def create_chat_router(db_path) -> APIRouter:
    """Create a router for the chat endpoint."""
    router = APIRouter()

    @router.post("/api/chat")
    async def chat(request: Request) -> dict:
        """Send a message to the LLM with optional RAG context."""
        body = await request.json()
        user_message = body.get("message", "")
        use_rag = body.get("use_rag", True)
        history = body.get("history", [])

        if not user_message:
            return {"error": "No message provided"}

        context_chunks = []
        sources: list[str] = []

        if use_rag:
            try:
                import lancedb

                _db = getattr(request.app.state, "db", None)
                _embedder = getattr(request.app.state, "embedding_service", None)
                if not _db or not _embedder:
                    from src.embeddings.embedding_service import create_embedding_service

                    _db = lancedb.connect(db_path)
                    _embedder = create_embedding_service()

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    if "child_chunks" in _db.table_names():
                        query_vector = _embedder.embed_query(user_message)
                        table = _db.open_table("child_chunks")
                        results = table.search(query_vector).limit(5).to_list()

                        for r in results:
                            content = r.get("content", "")
                            source = r.get("source_path", "unknown")
                            context_chunks.append(content)
                            if source not in sources:
                                sources.append(source)
            except Exception as e:
                logger.warning(f"RAG retrieval for chat failed: {e}")

        system_prompt = "You are a helpful assistant for a Personal Knowledge Management system. "
        if context_chunks:
            context_text = "\n\n---\n\n".join(context_chunks)
            system_prompt += (
                "Use the following retrieved documents to answer the user's question. "
                "Cite sources when relevant. If the documents don't contain the answer, "
                "say so.\n\n"
                f"Retrieved documents:\n{context_text}"
            )

        # Build user prompt from history + current message
        history_text = ""
        for h in history[-10:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            history_text += f"{role}: {content}\n"
        user_prompt = f"{history_text}user: {user_message}" if history_text else user_message

        try:
            from src.llm.provider import get_default_provider

            provider = get_default_provider()
            assistant_message = await provider.generate(system_prompt, user_prompt)

            return {
                "response": assistant_message,
                "sources": sources,
                "model": provider.config.model,
                "rag_used": bool(context_chunks),
            }
        except Exception as e:
            logger.error(f"Chat LLM call failed: {e}")
            return {"error": f"LLM call failed: {e}", "sources": sources}

    return router
