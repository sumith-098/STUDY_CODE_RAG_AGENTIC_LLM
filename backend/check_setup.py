"""
check_setup.py  --  Pehli baar chalane se pehle ye ek baar chalao:   python check_setup.py

Ye sirf 2 Gemini requests karta hai (1 chat + 1 embedding) aur batata hai ki
API key, chat model ID aur embedding model ID sahi hain ya nahi.
"""
from google import genai
from google.genai import types

from app import config


def main():
    if not config.GEMINI_API_KEY:
        print("X  GEMINI_API_KEY nahi mili. backend/.env banao (.env.example se copy karke).")
        return
    client = genai.Client(api_key=config.GEMINI_API_KEY)

    print(f"Chat model      : {config.CHAT_MODEL}")
    try:
        # generate_content(model, contents) -> response.text
        r = client.models.generate_content(model=config.CHAT_MODEL, contents="Reply with the word OK.")
        print("OK Chat chal raha hai. Jawab:", (r.text or "").strip()[:40])
    except Exception as e:
        print("X  Chat fail:", str(e)[:300])
        print("   -> AI Studio me model ka sahi ID dekho aur .env me GEMINI_CHAT_MODEL=... daalo.")

    print(f"Embedding model : {config.EMBEDDING_MODEL}")
    try:
        # embed_content(model, contents, config) -> response.embeddings[0].values (list of floats)
        e = client.models.embed_content(
            model=config.EMBEDDING_MODEL, contents=["hello"],
            config=types.EmbedContentConfig(output_dimensionality=config.EMBEDDING_DIMENSIONS))
        print(f"OK Embedding chal raha hai. Vector length: {len(e.embeddings[0].values)}")
    except Exception as ex:
        print("X  Embedding fail:", str(ex)[:300])
        print("   -> .env me GEMINI_EMBEDDING_MODEL=gemini-embedding-001 try karo.")


if __name__ == "__main__":
    main()
