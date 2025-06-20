import json
import time
from openai import OpenAI
from openai.types.shared_params import Reasoning
from openai.types.responses import Response, ResponseUsage, ResponseReasoningItem, ResponseFunctionToolCall

tools = [
    {
        "type": "function",
        "name": "store_memory",
        "description": "Store a memory for additional context in future turns.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key to store the memory under, added to the context for future turns."
                },
                "value": {
                    "type": "string",
                    "description": "The value to store in memory, which can be any relevant information to help the assistant in future turns."
                }
            },
            "required": ["key", "value"]
        }
    },
    {
        "type": "function",
        "name": "delete_memory",
        "description": "Delete a memory to remove it from future context.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key of the memory to delete."
                }
            },
            "required": ["key"]
        }
    }
]

class AssistantPlayer:
    def __init__(self, api_key: str, model_name: str, system_prompt: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model_name
        self.system_prompt = system_prompt
        self.history = []  # List of message dicts
        # Add system prompt as the first message
        self.history.append({"role": "system", "content": self.system_prompt})
        self.memory = {}  # Dictionary to store memories
        #delete the summary file if it exists, to start fresh
        try:
            with open("summary.txt", "w") as f:
                f.write("")
        except FileNotFoundError:
            pass

    def get_response(self, game_text: str) -> 'AssistantResponse':
        """
        Add the current turn, send the full message list to the Responses API, and return the assistant's reply as an AssistantResponse object.
        """
        # Remove old memory messages from history
        self.remove_old_memories_from_history(self.history)
        #self.remove_old_reasoning_from_history(self.history)
        self.history.append({"role": "system", "content": "Memory: " + json.dumps(self.memory)})  # Add the memory as the last message
        if game_text:
            self.history.append({"role": "user", "content": game_text})
        response = self.client.responses.create(
                model=self.model,
                input=self.history,  # type: ignore
                tools=tools,  # type: ignore
                tool_choice="auto",
                reasoning=Reasoning(effort="medium", summary="auto") if self.model.startswith("o") else None,
                timeout=30,
                store=True
            )
        return self.handle_response(response)
    
    def remove_old_memories_from_history(self, history: list):
        """
        Remove old memory messages from the history, so only the latest memory is used.
        This is necessary to avoid cluttering the history with multiple memory messages.
        """
        for message in history:
            if isinstance(message, dict) and message.get("role") == "system" and message.get("content", "").startswith("Memory: "):
                history.remove(message)

    def remove_old_reasoning_from_history(self, history: list):
        """
        Remove old reasoning messages from the history, preserving only the reasoning from the last user message onward.
        """
        user_message_found = False
        for message in reversed(history):
            if isinstance(message, dict) and message.get("role") == "user":
                user_message_found = True
            elif user_message_found and isinstance(message, ResponseReasoningItem):
                # Remove reasoning messages that are before the last user message
                history.remove(message)
            elif user_message_found and isinstance(message, ResponseFunctionToolCall):
                # Remove function call messages that are before the last user message
                history.remove(message)
            elif user_message_found and isinstance(message, dict) and message.get("type") == "function_call_output":
                # Remove function call output messages that are before the last user message
                history.remove(message)

    def handle_response(self, response: Response) -> 'AssistantResponse':
        """
        Handle the response from the LLM, extracting the command and message.
        """
        # Process the response
        command = None
        final_message = ''
        reasoning = ''
        for message in response.output:
            if message.type == "message":
                self.history.append(message)  # Store the message in history
                for content in message.content:
                    if content.type == "output_text":
                        command, stripped = self.extract_command(content.text)
                        final_message += stripped
                    elif content.type == "refusal":
                        final_message += content.refusal
            elif message.type == "reasoning":
                self.history.append(message)  # Store the reasoning in history
                for summary in message.summary:
                    reasoning += summary.text + '\n'
            elif message.type == "function_call":
                self.history.append(message)  # Store the function call in history
                function_name = message.name
                arguments = json.loads(message.arguments)
                function_response_text = self.handle_function_call(function_name, arguments)
                function_response = {
                    "type": "function_call_output",
                    "call_id": message.call_id,
                    "output": function_response_text
                }
                self.history.append(function_response)
        return AssistantResponse(command, final_message, reasoning, response.usage)
    
    def handle_function_call(self, function_name: str, arguments: dict) -> str:
        """
        Handle function calls from the LLM response.
        """
        if function_name == "store_memory":
            key = arguments.get("key")
            value = arguments.get("value")
            self.memory[key] = value
            return f"Memory stored: {key} = {value}"
        elif function_name == "delete_memory":
            key = arguments.get("key")
            if key in self.memory:
                del self.memory[key]
                return f"Memory deleted: {key}"
            else:
                return f"Memory not found: {key}"
        else:
            return f"Unknown function call: {function_name}"

    def extract_command(self, message: str) -> tuple[str | None, str]:
        """
        Extract the command from the response, in the <command></command> block.
        """
        start = message.find("<command>")
        if start != -1:
            end = message.find("</command>", start)
            if end != -1:
                command = message[start + len("<command>"):end].strip()
                # we also should remove the <command> tags and everything between them from the message
                message = message[:start] + message[end + len("</command>"):]
                return command, message.strip()
        return None, message.strip()  # Return empty command if not found
    
    def perform_summary(self, game_text: str) -> None:
        """
        Call an agent to summarize the entire history of the game and produce a smaller, simplified version of the history.
        This is useful for reducing the context size for future turns.
        """
        summary_prompt = ''
        with open("summary_prompt.txt", "r") as f:
            summary_prompt = f.read().strip()
        
        self.remove_old_memories_from_history(self.history)
        #self.remove_old_reasoning_from_history(self.history)
        history_copy = self.history.copy()  # Make a copy of the history to avoid modifying it
        if game_text:
            history_copy.append({"role": "user", "content": game_text})
        history_copy.append({"role": "system", "content": "Memory: " + json.dumps(self.memory)})  # Add the memory as the last message
        history_copy.append({"role": "user", "content": summary_prompt})

        success = False
        response = None
        while not success:
            try:
                response = self.client.responses.create(
                    model="o3",
                    input=history_copy,  # type: ignore
                    tools=[],  # type: ignore
                    tool_choice="none",
                    reasoning=Reasoning(effort="medium", summary=None),
                    timeout=300,
                    store=False
                )
                success = True
            except Exception as e:
                print(f"Error occurred: {e}")
                time.sleep(1)  # Wait before retrying
        if not response or not response.output_text:
            # no summary is available, so we just return and will keep our current history
            print("No summary available, keeping current history.")
            return
        summary = response.output_text
        # Replace unsupported characters
        safe_summary = summary.encode("ascii", errors="replace").decode("ascii")
        # dump out the summary to a file for debugging purposes, appending to the file
        with open("summary.txt", "a") as f:
            f.write("\n--- Summary ---\n")
            f.write(safe_summary)
        # Clear the history and start fresh with the summary
        self.history = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": summary}]

class AssistantResponse:
    def __init__(self, command: str | None, message: str, reasoning: str, usage: ResponseUsage | None):
        self.command = command
        self.message = message
        self.reasoning = reasoning
        
        self.total_tokens = usage.total_tokens if usage else 0
        self.output_tokens = usage.output_tokens if usage else 0
        self.input_tokens = usage.input_tokens if usage else 0
        self.cached_input_tokens = usage.input_tokens_details.cached_tokens if usage and usage.input_tokens_details else 0

