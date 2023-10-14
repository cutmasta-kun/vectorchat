import chromadb
from chromadb.config import Settings
from pprint import pprint as pp


persist_directory = "chromadb"
chroma_client = chromadb.PersistentClient(path=persist_directory)
collection = chroma_client.get_or_create_collection(name="knowledge_base")


print('KB presently has %s entries' % collection.count())
print('\n\nBelow are the top 10 entries:')
results = collection.peek()
pp(results)