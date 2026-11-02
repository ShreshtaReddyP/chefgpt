ChefGPT
ChefGPT is a generative-AI recipe assistant that turns a dish idea and dietary constraints into a recipe. It is designed to help users explore meal ideas while checking the recipe against the constraints they provide.
Features
- Generate a recipe from a dish, ingredient, or meal idea.
- Add dietary constraints (for example, “no dairy”).
- View recipe details in a responsive web interface.
- Check off ingredients while cooking.
- Display a food photo when a suitable image is available.
- Cache photo lookups to reduce repeated requests.
Note: AI-generated recipes may contain mistakes. Check ingredients, allergens, and cooking temperatures before preparing or eating a dish.

Tech stack
- Python
- FastAPI — web server and recipe endpoint
- Pydantic — request validation
- HTML, CSS, JavaScript — browser interface
- Gemini — generative AI used by the recipe pipeline
- Pixabay API — optional food-photo search
Project structure
The exact structure may vary by checkout. The application entry point used for deployment is api.py.
chefgpt/
├── api.py
├── requirements.txt
├── .env                 # local secrets; do not commit
└── chefgpt/
    └── pipeline.py      # recipe generation pipeline
The web page is served from GET /. Recipe generation is handled by POST /recipe, which passes the submitted dish and constraints to the pipeline. The optional GET /photo endpoint searches for food photos.
Getting started
1. Clone the repository
git clone <YOUR_REPOSITORY_URL>
cd chefgpt
Replace <YOUR_REPOSITORY_URL> with the repository's Git URL.
2. Create and activate a virtual environment
Windows (PowerShell):
py -m venv .venv
.\.venv\Scripts\Activate.ps1
macOS / Linux:
python3 -m venv .venv
source .venv/bin/activate
3. Install dependencies
python -m pip install -r requirements.txt
4. Configure environment variables
Create a .env file in the project root and add your API key:
GEMINI_API_KEY=your_gemini_api_key
For food-photo search, you can also add:
PIXABAY_API_KEY=your_pixabay_api_key
The Pixabay key is optional. Without it, recipe generation can still work, but food photos may not be returned.

Make sure .env is listed in .gitignore. Never commit API keys or share them publicly.
5. Run the application
uvicorn api:app --reload
Open the local address shown in the terminal (typically http://127.0.0.1:8000).
Deploying on Render
A typical Render Web Service configuration for this project:
- Build command: pip install -r requirements.txt
- Start command: uvicorn api:app --host 0.0.0.0 --port $PORT
- Environment variables: add GEMINI_API_KEY in the Render service's Environment settings. Add PIXABAY_API_KEY if you want food-photo search.
Keep the repository root directory blank if api.py and requirements.txt are in the repository root.
API overview
GET /
Returns the ChefGPT web interface.
POST /recipe
Generates a recipe from the provided dish request and dietary constraints.

Example request:
{
  "request": "chicken pasta",
  "constraints": "no dairy"
}
The response is the result returned by the recipe-generation pipeline. Its exact fields depend on the pipeline implementation.
GET /photo
Looks for a matching food photo. The endpoint accepts one or more q search phrases. It returns a photo URL when a suitable result is found, or null if no match is available.
Troubleshooting
- The app starts but recipe generation fails: confirm GEMINI_API_KEY is set in the environment where the server is running.
- The app works locally but not on Render: check the Render service logs and environment variables.
- No food photo appears: confirm PIXABAY_API_KEY is configured. Photo lookup is optional and may return no result.
- Dependency or import errors: activate the virtual environment and reinstall dependencies using python -m pip install -r requirements.txt.
Safety and limitations
ChefGPT is an educational AI recipe assistant, not a substitute for professional nutrition or medical advice. Always verify allergens and dietary suitability yourself. AI outputs can be inaccurate or incomplete.
License
No license is specified here. Add a license file if you intend to distribute or reuse this project publicly.
Chefgpt Homepage:
<img width="1391" height="786" alt="image" src="https://github.com/user-attachments/assets/d6627b1c-720e-43cf-8b6a-f0422569522c" />
<img width="1392" height="842" alt="image" src="https://github.com/user-attachments/assets/5d10e027-81af-40b7-b837-98b774c74786" />
<img width="1392" height="852" alt="image" src="https://github.com/user-attachments/assets/4468a6a4-de43-4eba-af0b-19e8a65f949a" />


