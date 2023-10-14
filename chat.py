# chat.py

import os
import yaml
import openai
import sys
from uuid import uuid4
from time import time, sleep
from collections import deque
import chromadb
from chromadb.config import Settings

# Function to validate the API key
def validate_api_key(api_key):
    if not api_key:
        raise ValueError("API key is missing.")

# Function to validate file existence
def validate_file_existence(filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"The file {filepath} does not exist.")

# Function to validate API responses
def validate_api_response(response):
    if 'choices' not in response or not response['choices']:
        raise ValueError("Invalid API response.")

# Function to validate database state
def validate_database(collection):
    if collection.count() < 0:
        raise ValueError("Database is not initialized correctly.")

# Function to read a file, ensuring it exists
def open_file(filepath):
    validate_file_existence(filepath)
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as infile:
        return infile.read()

# Function to save data to a file, ensuring the directory exists
def save_file(filename, content):
    directory, file = os.path.split(filename)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    with open(filename, 'w') as f:
        f.write(content)

# Function to save data to a YAML file
def _save_yaml(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as file:
        yaml.dump(data, file, allow_unicode=True)

# Function to interact with the chatbot API
def chatbot(messages, model="gpt-4", temperature=0):
    max_retry = 7
    retry = 0
    while True:
        try:
            response = openai.ChatCompletion.create(model=model, messages=messages, temperature=temperature)
            validate_api_response(response)
            text = response['choices'][0]['message']['content']
            debug_object = [i['content'] for i in messages]
            debug_object.append(text)
            _save_yaml(f'api_logs/convo_{time()}.yaml', debug_object)
            if response['usage']['total_tokens'] >= 7000:
                messages.pop(1)
            return text
        except Exception as oops:
            if 'maximum context length' in str(oops):
                messages.pop(1)
                continue
            retry += 1
            if retry >= max_retry:
                raise ConnectionError("Max retries reached. Exiting.")
            sleep(2 ** (retry - 1) * 5)

# Main function to run the chat application
def main(api_key):
    try:
        # Validate the API key
        validate_api_key(api_key)
        
        # Set up the database client
        persist_directory = "chromadb"
        chroma_client = chromadb.PersistentClient(path=persist_directory)
        collection = chroma_client.get_or_create_collection(name="knowledge_base")
        validate_database(collection)

        # Set the API key for the OpenAI API
        openai.api_key = api_key

        # Initialize the conversation and user messages deques
        conversation = deque([{'role': 'system', 'content': open_file('system_default.txt')}], maxlen=5)
        user_messages = deque(maxlen=3)
        
        # Main chat loop
        while True:
            text = input('\n\nUSER: ')
            user_messages.append(text)
            conversation.append({'role': 'user', 'content': text})
            save_file(f'chat_logs/chat_{time()}_user.txt', text)
            main_scratchpad = '\n\n'.join([f'USER: {um}' for um in user_messages]).strip()
            current_profile = open_file('user_profile.txt')
            kb = 'No KB articles yet'
            if collection.count() > 0:
                results = collection.query(query_texts=[main_scratchpad], n_results=1)
                kb = results['documents'][0][0]
            default_system = (open_file('system_default.txt')).replace('<<PROFILE>>', current_profile).replace('<<KB>>', kb)
            conversation[0]['content'] = default_system
            response = chatbot(list(conversation))
            save_file(f'chat_logs/chat_{time()}_chatbot.txt', response)
            conversation.append({'role': 'assistant', 'content': response})
            
            
            print(f'\n\nCHATBOT: {response}')
            
            
            print('\n\nUpdating user profile...')
            profile_length = len(current_profile.split(' '))
            profile_conversation = [
                {'role': 'system', 'content': (open_file('system_update_user_profile.txt')).replace('<<PROFILE>>', current_profile).replace('<<WORDS>>', str(profile_length))},
                {'role': 'user', 'content': main_scratchpad}
            ]
            current_profile = chatbot(profile_conversation)
            save_file('user_profile.txt', current_profile)
            
            print('\n\nUpdating knowledge base...')
            handle_knowledge_base_update(collection, main_scratchpad)
    
    except ValueError as ve:
        print(f"Validation Error: {str(ve)}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as fnfe:
        print(f"File Error: {str(fnfe)}", file=sys.stderr)
        sys.exit(1)
    except ConnectionError as ce:
        print(f"Connection Error: {str(ce)}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {str(e)}", file=sys.stderr)
        sys.exit(1)

def add_new_document_to_collection(collection, main_scratchpad):
    # Ensuring the file needed for conversation exists
    validate_file_existence('system_instantiate_new_kb.txt')
    
    kb_convo = [
        {'role': 'system', 'content': open_file('system_instantiate_new_kb.txt')},
        {'role': 'user', 'content': main_scratchpad}
    ]
    article = chatbot(kb_convo)
    new_id = str(uuid4())
    collection.add(documents=[article], ids=[new_id])
    save_file(f'db_logs/log_{time()}_add.txt', f'Added document {new_id}:\n{article}')

def update_existing_document_in_collection(collection, main_scratchpad, kb, kb_id):
    # Ensuring the file needed for conversation exists
    validate_file_existence('system_update_existing_kb.txt')
    
    kb_convo = [
        {'role': 'system', 'content': open_file('system_update_existing_kb.txt').replace('<<KB>>', kb)},
        {'role': 'user', 'content': main_scratchpad}
    ]
    article = chatbot(kb_convo)
    collection.update(ids=[kb_id], documents=[article])
    save_file(f'db_logs/log_{time()}_update.txt', f'Updated document {kb_id}:\n{article}')

    # Check if the article needs to be split and updated
    kb_len = len(article.split(' '))
    if kb_len > 1000:
        split_and_update_document(collection, article, kb_id)

def split_and_update_document(collection, article, kb_id):
    # Ensuring the file needed for conversation exists
    validate_file_existence('system_split_kb.txt')
    
    kb_convo = [
        {'role': 'system', 'content': open_file('system_split_kb.txt')},
        {'role': 'user', 'content': article}
    ]
    articles = chatbot(kb_convo).split('ARTICLE 2:')
    a1 = articles[0].replace('ARTICLE 1:', '').strip()
    a2 = articles[1].strip()
    collection.update(ids=[kb_id], documents=[a1])
    new_id = str(uuid4())
    collection.add(documents=[a2], ids=[new_id])
    save_file(f'db_logs/log_{time()}_split.txt', f'Split document {kb_id}, added {new_id}:\n{a1}\n\n{a2}')

def handle_knowledge_base_update(collection, main_scratchpad):
    if collection.count() == 0:
        add_new_document_to_collection(collection, main_scratchpad)
    else:
        results = collection.query(query_texts=[main_scratchpad], n_results=1)
        kb = results['documents'][0][0]
        kb_id = results['ids'][0][0]
        update_existing_document_in_collection(collection, main_scratchpad, kb, kb_id)

if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            print("API key is required. Exiting.")
            sys.exit(1)

        api_key = sys.argv[1]
        main(api_key)
    except KeyboardInterrupt:
        sys.exit(0)
