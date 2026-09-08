import chromadb
from sentence_transformers import SentenceTransformer

client = chromadb.PersistentClient(path="C:/Users/20866/Desktop/trpg-project/trpg-server/chroma_db")
model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
memory = client.create_collection(name="memory")

memories = ["这是一个TRPG游戏"]
doc_embeddings = model.encode(memories).tolist()

metadata=[{"type": "information","time": "1220-01-01"}]
ids=["memory_1"]

memory.add(
    documents=memories,
    embeddings=doc_embeddings,
    metadatas=metadata,
    ids=ids
)

print("Success")