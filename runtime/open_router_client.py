
import os
from pathlib import Path


try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*a, **kw): pass
    
load_dotenv(Path(__file__).parent / ".env")

def cliente_open_router():
    chave_api = os.environ.get("OPENROUTER_API_KEY")
    from openai import OpenAI
    cliente = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=chave_api,
        timeout=60.0,
        max_retries=1
    )
    return cliente

def enviar_mensagem_system_user_para_open_router(systemPrompt, userPrompt):
    cliente = cliente_open_router()
    modeloLLM = os.environ.get("OPENROUTER_MODEL")
    resposta = cliente.chat.completions.create(
        model=modeloLLM,
        messages=[
            {"role": "system", "content": systemPrompt},
            {"role": "user", "content": userPrompt},
        ]
    )
    return resposta   

def enviar_mensagem_user_para_open_router(userPrompt):
    cliente = cliente_open_router()
    modeloLLM = os.environ.get("OPENROUTER_MODEL")
    resposta = cliente.chat.completions.create(
        model=modeloLLM,
        messages=[
            {"role": "user", "content": userPrompt},
        ]
    )
    return resposta

