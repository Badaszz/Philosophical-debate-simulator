from langgraph.graph import StateGraph
from typing import TypedDict
from dotenv import load_dotenv
from typing import TypedDict, List
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()



model = "openai/gpt-oss-20b"

from langchain_groq import ChatGroq

llm = ChatGroq(
    model=model,
    temperature=0.0,
    max_retries=2,
    # other params...
)

# State definitions
class InputState(TypedDict):
    topic: str

class OutputState(TypedDict):
    topic: str
    response: str

def passthrough(state: InputState) -> OutputState:
    llm_response = llm.invoke(f"Provide a philosophical insight on the topic: {state['topic']}")
    return {
        "topic": state["topic"],
        "response": llm_response.content
    }

graph = StateGraph(InputState, output=OutputState)
graph.add_node("start", passthrough)
graph.set_entry_point("start")
graph.set_finish_point("start")

philosophy_agent = graph.compile()
