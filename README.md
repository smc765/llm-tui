# llm-tui

A simple terminal UI for [llm](https://github.com/simonw/llm).  

<img width="1920" height="900" alt="demo0" src="https://github.com/user-attachments/assets/cefba88a-3391-433d-b37c-81b291411ad9" />

## Setup

### 1. Setup Virtual Environment (Optional)

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

### 4. Install Extensions (Optional) 

```bash
llm install llm-anthropic
```

```bash
llm install llm-deepseek
```

```bash
llm install llm-grok
```

## Usage

    python main.py

## Additional Configuration

### Example `.env` file:

```bash
MODEL_OPTIONS={"temperature": 1.0, "max_tokens": 1000, "max_completion_tokens": 1000}
DEFAULT_MODEL="gpt-4o"
DEFAULT_SYSTEM_PROMPT="system prompt here"
```
