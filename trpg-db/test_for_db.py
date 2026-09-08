import chromadb
from sentence_transformers import SentenceTransformer

#Qwen/Qwen3-Embedding-0.6B
#paraphrase-multilingual-MiniLM-L12-v2

client = chromadb.PersistentClient(path="C:/Users/20866/Desktop/trpg-project/trpg-server/chroma_db")
memory = client.get_collection(name="memory")
model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

memories = ["云舟带着他妹妹下山求医去了，入秋前走的，说是往东边寻一位名医。如今山高路远，去了哪里，连听海生也不一定说得准。",
            "如今是嘉定十三年正月初一，入秋是去年八九月间——叶云舟兄妹下山已近四个月了。",
            "云舟入点苍那年，还是个病得快要撑不住的少年。他那妹妹——更是打娘胎里就带着病根，一身真气躁乱不安，连寻常大夫都诊不出个所以然。是我和听海生用两仪剑气替他们兄妹镇着，才勉强养住了一条命。"]

metadata=[{"type": "event","time": "1220-01-01"},{"type": "event","time": "1220-01-01"},{"type": "event","time": "1220-01-01"}]

ids=[f"memory_{i}" for i in range(2, 5)]

doc_embeddings = model.encode(memories).tolist()

memory.add(
    embeddings=doc_embeddings,
    documents=memories,
    metadatas=metadata,
    ids=ids
)

while True:
    query = input(">>> ")
    query_embedding = model.encode([query]).tolist()

    results = memory.query(
        query_embeddings=query_embedding,
        n_results=3
    )
    print(results)