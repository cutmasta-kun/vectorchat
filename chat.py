import os
import yaml
import requests
from uuid import uuid4
from time import time, sleep
from collections import deque
import chromadb
from chromadb.config import Settings
import openai

def _save_yaml(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as file:
        yaml.dump(data, file, allow_unicode=True)

def save_file(filename, content):
    directory, file = os.path.split(filename)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    with open(filename, 'w') as f:
        f.write(content)

def open_file(filepath):
    if not os.path.exists(filepath):
        save_file(filepath, '')
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as infile:
        return infile.read()

def chatbot(messages, model="gpt-4", temperature=0):
    max_retry = 7
    retry = 0
    while True:
        try:
            response = openai.ChatCompletion.create(model=model, messages=messages, temperature=temperature)
            text = response['choices'][0]['message']['content']
            debug_object = [i['content'] for i in messages]
            debug_object.append(text)
            _save_yaml('api_logs/convo_%s.yaml' % time(), debug_object)
            if response['usage']['total_tokens'] >= 7000:
                a = messages.pop(1)
            return text
        except Exception as oops:
            if 'maximum context length' in str(oops):
                a = messages.pop(1)
                continue
            retry += 1
            if retry >= max_retry:
                exit(1)
            sleep(2 ** (retry - 1) * 5)

def main():
    persist_directory = "chromadb"
    chroma_client = chromadb.Client(Settings(persist_directory=persist_directory,chroma_db_impl="duckdb+parquet",))
    collection = chroma_client.get_or_create_collection(name="knowledge_base")
    openai.api_key = open_file('key_openai.txt')
    conversation = deque([{'role': 'system', 'content': open_file('system_default.txt')}], maxlen=5)  # Automatically removes older items.
    user_messages = deque(maxlen=3)  # Automatically removes older items.
    while True:
        text = input('\n\nUSER: ')
        user_messages.append(text)
        conversation.append({'role': 'user', 'content': text})
        save_file('chat_logs/chat_%s_user.txt' % time(), text)
        main_scratchpad = '\n\n'.join(['USER: ' + um for um in user_messages]).strip()
        current_profile = open_file('user_profile.txt')
        kb = 'No KB articles yet'
        if collection.count() > 0:
            results = collection.query(query_texts=[main_scratchpad], n_results=1)
            kb = results['documents'][0][0]
        default_system = (open_file('system_default.txt')).replace('<<PROFILE>>', current_profile).replace('<<KB>>', kb)
        conversation[0]['content'] = default_system
        response = chatbot(list(conversation))
        save_file('chat_logs/chat_%s_chatbot.txt' % time(), response)
        conversation.append({'role': 'assistant', 'content': response})
        print('\n\nCHATBOT: %s' % response)
        print('\n\nUpdating user profile...')
        profile_length = len(current_profile.split(' '))
        profile_conversation = [{'role': 'system', 'content': (open_file('system_update_user_profile.txt')).replace('<<PROFILE>>', current_profile)}, {'role': 'user', 'content': main_scratchpad}]
        current_profile = chatbot(profile_conversation)
        save_file('user_profile.txt', current_profile)
        print('\n\nUpdating knowledge base...')
        handle_knowledge_base_update(collection, main_scratchpad)

def handle_knowledge_base_update(collection, main_scratchpad):
    if collection.count() == 0:
        kb_convo = [{'role': 'system', 'content': open_file('system_instantiate_new_kb.txt')}, {'role': 'user', 'content': main_scratchpad}]
        article = chatbot(kb_convo)
        new_id = str(uuid4())
        collection.add(documents=[article], ids=[new_id])
        save_file('db_logs/log_%s_add.txt' % time(), 'Added document %s:\n%s' % (new_id, article))
    else:
        results = collection.query(query_texts=[main_scratchpad], n_results=1)
        kb = results['documents'][0][0]
        kb_id = results['ids'][0][0]
        kb_convo = [{'role': 'system', 'content': open_file('system_update_existing_kb.txt').replace('<<KB>>', kb)}, {'role': 'user', 'content': main_scratchpad}]
        article = chatbot(kb_convo)
        collection.update(ids=[kb_id], documents=[article])
        save_file('db_logs/log_%s_update.txt' % time(), 'Updated document %s:\n%s' % (kb_id, article))
        kb_len = len(article.split(' '))
        if kb_len > 1000:
            kb_convo = [{'role': 'system', 'content': open_file('system_split_kb.txt')}, {'role': 'user', 'content': article}]
            articles = chatbot(kb_convo).split('ARTICLE 2:')
            a1 = articles[0].replace('ARTICLE 1:', '').strip()
            a2 = articles[1].strip()
            collection.update(ids=[kb_id], documents=[a1])
            new_id = str(uuid4())
            collection.add(documents=[a2], ids=[new_id])
            save_file('db_logs/log_%s_split.txt' % time(), 'Split document %s, added %s:\n%s\n\n%s' % (kb_id, new_id, a1, a2))

if __name__ == '__main__':
    main()
