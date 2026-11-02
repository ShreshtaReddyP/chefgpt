
# ChefGPT — AI Recipe Assistant

**Turn a meal idea into a recipe that respects your dietary constraints.**

ChefGPT is a generative-AI recipe assistant that combines recipe generation with dietary constraint evaluation. Enter a dish and your requirements, and ChefGPT generates a recipe designed around them.

<!-- Replace with your actual screenshot or GIF -->
![ChefGPT Demo] ## Demo
## Demo

https://github.com/user-attachments/assets/b81f1711-ea06-44b0-8594-fc60ee65fd14



---

## Why ChefGPT?

AI can generate recipes quickly—but a recipe can still include ingredients a user wants to avoid.

ChefGPT explores a more constraint-aware approach: generate a recipe from the user's request, then evaluate it against the dietary requirements provided.

## Features

- **AI recipe generation** — create recipes from a dish, ingredient, or meal idea.
- **Dietary constraints** — provide requirements such as “no dairy.”
- **Constraint evaluation** — check the generated recipe against the supplied constraints.
- **Cooking-friendly interface** — view recipe details and check off ingredients while cooking.
- **Food imagery** — display a matching food photo when one is available.
- **Photo lookup caching** — reduce repeated photo searches.

## How It Works

```text
Dish Idea + Dietary Constraints
              │
              ▼
      Constraint Parsing
              │
              ▼
       Recipe Generation
              │
              ▼
      AI Audit + Rule Audit
              │
              ▼
       Repair Loop (if needed)
              │
              ▼
       Recipe for the User
```

The pipeline is designed to evaluate generated recipes against the user's constraints. AI-generated content can still be inaccurate, so the result should be checked before use.

## Tech Stack

| Component | Technology |
|---|---|
| Backend | Python, FastAPI |
| Request validation | Pydantic |
| Generative AI | Gemini |
| Frontend | HTML, CSS, JavaScript |
| Food photo search | Pixabay API |

## Run Locally

### 1. Clone the repository

```bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd chefGPT
```

### 2. Install dependencies

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

macOS / Linux:

```bash
source venv/bin/activate
```

```bash
python -m pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key
PIXABAY_API_KEY=your_pixabay_api_key
```

The Pixabay key is optional if you do not need food-photo search.

### 4. Start the application

```bash
uvicorn api:app --reload
```

Open `http://127.0.0.1:8000` in your browser.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Serve the web interface |
| `POST` | `/recipe` | Generate a recipe |
| `GET` | `/photo` | Search for a food photo |

Example recipe request:

```json
{
  "request": "chicken pasta",
  "constraints": "no dairy"
}
```

## Deployment

ChefGPT can be deployed as a Render Web Service.

**Build command**

```bash
pip install -r requirements.txt
```

**Start command**

```bash
uvicorn api:app --host 0.0.0.0 --port $PORT
```

Configure `GEMINI_API_KEY` in the Render environment settings. Add `PIXABAY_API_KEY` if photo search is enabled.

## Limitations

ChefGPT is an educational project. Generated recipes may contain errors or omit relevant dietary details. Always verify ingredients, allergens, and cooking temperatures before preparing or eating a recipe. It is not a substitute for professional medical or nutrition advice.

---

**Built as a hands-on project in generative AI, prompt engineering, and constraint-aware recipe generation.**

Chefgpt Homepage:
<img width="1391" height="786" alt="image" src="https://github.com/user-attachments/assets/d6627b1c-720e-43cf-8b6a-f0422569522c" />
<img width="1392" height="842" alt="image" src="https://github.com/user-attachments/assets/5d10e027-81af-40b7-b837-98b774c74786" />
<img width="1392" height="852" alt="image" src="https://github.com/user-attachments/assets/4468a6a4-de43-4eba-af0b-19e8a65f949a" />


