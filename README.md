# ChefGPT
Prompt-engineered recipe assistant: parse constraints -> generate -> LLM audit + rule audit -> repair loop.

    pip install -r requirements.txt
    export GEMINI_API_KEY=...
    python main.py "pad thai" "vegan, peanut allergy, under 600 cal"
    pytest tests/
