from fastapi import FastAPI
import uvicorn
from langserve import add_routes
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
import os
import dotenv

dotenv.load_dotenv()

# FIX: correct getenv usage
os.environ["GROQ_API_KEY"] ="*********"

app = FastAPI(
    title="LANGCHAIN SERVER",
    description="simple api server",
    version="1.0"
)

# General API
prompt_general_final = ChatPromptTemplate.from_template(
    "You are a professional investment advisor.\n\n"
    "Based on the following information:\n"
    "- Market Summary: {take_actual_summary}\n"
    "- Company Details: {main_output}\n\n"
    "Provide a clear and structured evaluation covering:\n"
    "1. Investment Recommendation (Buy / Hold / Sell)\n"
    "2. Reasons for your decision\n"
    "3. Short-term outlook (1–3 months)\n"
    "4. Long-term outlook (1–3 years)\n"
    "5. Key risks and opportunities\n\n"
    "Give the final answer in a clean, professional, and easy-to-read format."
)


add_routes(
    app=app,
    runnable=  prompt_general_final | ChatGroq(
        model="qwen/qwen3-32b",
        temperature=0.0,
        max_retries=2
    ),
    path="/openai"
)

# LLM instance
llm_openai = ChatGroq(
    model="qwen/qwen3-32b",
    temperature=0.0,
    max_retries=2
)

# FIX: proper templating syntax
prompt = ChatPromptTemplate.from_template(
    "What are the topics {topic}? Provide detailed market research from web search."
)

prompt1 = ChatPromptTemplate.from_template(
    "Create a summary for the given topic: {topic}"
)

# Market Research Route
add_routes(
    app=app,
    runnable=prompt | llm_openai,
    path="/market"
)

# Summary Route
add_routes(
    app=app,
    runnable=prompt1 | llm_openai,
    path="/summary"
)

if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8000)
