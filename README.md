# llm-tui

A simple terminal UI for [llm](https://github.com/simonw/llm).  

## Setup

### 1. Create Virtual Environment (Optional)

```bash
python -m venv ./.venv
```

```bash
./.venv/Scripts/Activate.ps1
```

### 2. Install Dependencies

    pip install -r requirements.txt

#### Install [Pandoc](https://github.com/jgm/pandoc/releases/tag/3.9.0.2)

### 3. Set API Keys

    llm keys set openai

Or create a `.env` file in the same directory as `main.py` containing any the following lines:

```bash
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
LLM_DEEPSEEK_KEY=your_key_here
XAI_API_KEY=your_key_here
```

## Usage

    python main.py

## Additional Configuration

### Example `.env` file:

```bash
MODEL_OPTIONS={"temperature": 1.0, "max_tokens": 1000, "reasoning_effort": "high"}
DEFAULT_MODEL="gpt-5-nano"
DEFAULT_SYSTEM_PROMPT="You are an expert AI assistant."
```
