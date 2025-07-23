import importlib
from langchain_core.messages import SystemMessage, HumanMessage

SYSTEM_MESSAGE = (
    "You are a text analyser who will attempt to give the most concise information "
    "to the request, the information should be returned in a way that if I ask you again "
    "I should get the same answer if the outcome is the same. The goal is to cut down "
    "or reduce the text changes from you when i ask the same question about similar content "
    "Always list items in exactly the same order and wording as found in the source text. "
)


class LLM_integrate:
    PROVIDER_MAP = {
        "openai": ("langchain_openai", "ChatOpenAI"),
        "azure": ("langchain_community.chat_models", "AzureChatOpenAI"),
        "gemini": ("langchain_google_genai", "ChatGoogleGenerativeAI")
    }

    def __init__(self, api_keys: dict):
        """
        api_keys = {
            "openai": "sk-xxx",
            "azure": "AZURE_KEY",
            "gemini": "GEMINI_KEY"
        }
        """
        self.api_keys = api_keys

    def run(self, provider: str, model: str, message: str):
        module_name, class_name = self.PROVIDER_MAP[provider]

        # Import the class dynamically
        module = importlib.import_module(module_name)
        LLMClass = getattr(module, class_name)

        # Create the LLM object
        llm_kwargs = {}
        if provider == "openai":
            llm_kwargs = dict(api_key=self.api_keys.get("openai", ''),
                              model=model,
                              # https://api.python.langchain.com/en/latest/chat_models/langchain_openai.chat_models.base.ChatOpenAI.html#langchain_openai.chat_models.base.ChatOpenAI.temperature
                              temperature=0 # most deterministic,
                              )
        elif provider == "azure":
            llm_kwargs = dict(
                api_key=self.api_keys["azure"],
                azure_endpoint="https://<your-endpoint>.openai.azure.com",
                deployment_name=model
            )
        elif provider == "gemini":
            llm_kwargs = dict(api_key=self.api_keys.get("gemini"), model=model)

        llm = LLMClass(**llm_kwargs)

        # Build your messages
        messages = [
            SystemMessage(content=SYSTEM_MESSAGE),
            HumanMessage(content=message)
        ]

        # Run the model asynchronously
        result = llm.invoke(messages)
        return result.content
