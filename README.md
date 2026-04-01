# llm-tui

## Setup

### 1. Setup Virtual Enviornment (Optional)

```powershell
python -m venv ./.venv
```

```powershell
./.venv/Scripts/Activate.ps1
```

### 2. Install Dependencies

    pip install -r requirements.txt

#### [Pandoc](https://github.com/jgm/pandoc/releases/tag/3.9.0.2)

### 3. Set API Keys

    llm keys set openai

Or create a `.env` file with any of the following

    OPENAI_API_KEY=your_key_here
    ANTHROPIC_API_KEY=your_key_here
    LLM_DEEPSEEK_KEY=your_key_here
    XAI_API_KEY=your_key_here

### 4. Install Extensions (Optional)

- Claude  

      llm install llm-anthropic

- Deepseek  

      llm install llm-deepseek

- Grok  

      llm install llm-grok


## Usage

    python main.py