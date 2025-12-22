"""
Cookidoo Recipe Creator - Streamlit UI with Gemini AI

A chat interface for creating Thermomix recipes using Gemini AI with Cookidoo tools.
"""

import streamlit as st
import asyncio
import json
import re
import httpx
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.generativeai.types import FunctionDeclaration, Tool
from cookidoo_service import CookidooService
from schemas import CustomRecipe

# Page configuration
st.set_page_config(
    page_title="Cookidoo Recipe Creator",
    page_icon="🍳",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for premium look
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    .main {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    
    .stApp {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    }
    
    h1 {
        background: linear-gradient(90deg, #00d4aa, #00b4d8, #7209b7);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-weight: 700 !important;
        text-align: center;
        padding: 1rem 0;
    }
    
    h2, h3 {
        color: #e0e0e0 !important;
        font-weight: 600 !important;
    }
    
    .stTextInput > div > div > input,
    .stTextArea > div > div > textarea {
        background: rgba(255, 255, 255, 0.08) !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
        border-radius: 12px !important;
        color: #ffffff !important;
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #00d4aa 0%, #00b4d8 100%) !important;
        color: #1a1a2e !important;
        border: none !important;
        border-radius: 12px !important;
        padding: 0.75rem 2rem !important;
        font-weight: 600 !important;
    }
    
    .stChatMessage {
        background: rgba(255, 255, 255, 0.05) !important;
        border-radius: 16px !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
    }
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ==================== TOOL FUNCTIONS ====================

def scrape_recipe_from_url(url: str) -> dict:
    """Scrape recipe details from any recipe website."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        result = {
            "name": "",
            "servings": 4,
            "total_time": 60,
            "ingredients": [],
            "steps": [],
            "source_url": url
        }
        
        # Try JSON-LD structured data first
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            data = item
                            break
                    else:
                        continue
                
                if '@graph' in data:
                    for item in data['@graph']:
                        if isinstance(item, dict) and item.get('@type') == 'Recipe':
                            data = item
                            break
                    else:
                        continue
                
                if data.get('@type') == 'Recipe':
                    result['name'] = data.get('name', '')
                    
                    yield_val = data.get('recipeYield')
                    if yield_val:
                        if isinstance(yield_val, list):
                            yield_val = yield_val[0]
                        match = re.search(r'(\d+)', str(yield_val))
                        if match:
                            result['servings'] = int(match.group(1))
                    
                    total_time = data.get('totalTime') or data.get('cookTime')
                    if total_time:
                        hours = re.search(r'(\d+)H', str(total_time))
                        minutes = re.search(r'(\d+)M', str(total_time))
                        total_mins = 0
                        if hours:
                            total_mins += int(hours.group(1)) * 60
                        if minutes:
                            total_mins += int(minutes.group(1))
                        if total_mins > 0:
                            result['total_time'] = total_mins
                    
                    ingredients = data.get('recipeIngredient', [])
                    if isinstance(ingredients, list):
                        result['ingredients'] = [str(ing).strip() for ing in ingredients if ing]
                    
                    instructions = data.get('recipeInstructions', [])
                    if isinstance(instructions, list):
                        for step in instructions:
                            if isinstance(step, str):
                                result['steps'].append(step.strip())
                            elif isinstance(step, dict):
                                text = step.get('text') or step.get('name', '')
                                if text:
                                    result['steps'].append(str(text).strip())
                    
                    if result['name']:
                        return result
            except:
                continue
        
        # Fallback to HTML parsing
        title_tag = soup.find('h1') or soup.find('title')
        if title_tag:
            result['name'] = title_tag.get_text(strip=True)
        
        return result
        
    except Exception as e:
        return {"error": str(e)}


async def upload_to_cookidoo(name: str, ingredients: list, steps: list, servings: int = 4, prep_time: int = 30, total_time: int = 60, hints: list = None) -> dict:
    """Upload a custom recipe to Cookidoo."""
    try:
        email = st.secrets["cookidoo_email"]
        password = st.secrets["cookidoo_password"]
        
        service = CookidooService(email, password)
        api = await service.login()
        
        recipe_id = await service.create_custom_recipe(
            name=name,
            ingredients=ingredients,
            steps=steps,
            servings=servings,
            prep_time=prep_time,
            total_time=total_time,
            hints=hints
        )
        
        localization = api.localization
        base_url = localization.url
        if not base_url.startswith('http'):
            base_url = f"https://{base_url}"
        if '/foundation/' in base_url:
            base_url = base_url.split('/foundation/')[0]
        recipe_url = f"{base_url}/created-recipes/{recipe_id}"
        
        await service.close()
        
        return {
            "success": True,
            "recipe_id": recipe_id,
            "url": recipe_url
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==================== GEMINI SETUP ====================

SYSTEM_PROMPT = """Tu es un expert culinaire spécialisé dans la création de recettes pour le Thermomix. Tu as une parfaite compréhension de ses modes, accessoires et comment écrire des instructions claires et précises.

## Directives pour écrire des recettes Thermomix

Chaque étape doit utiliser le vocabulaire spécifique du Thermomix :
- **Vitesse** : vitesse 1, vitesse 5, vitesse 🥄 (mijotage), sens inverse 🔄
- **Température** : 50°C, 100°C, 120°C, Varoma
- **Temps** : 5 min, 30 sec
- **Fonctions** : Mode pétrissage 🌾, Turbo, Mixer
- **Accessoires** : fouet papillon, panier de cuisson, spatule

Exemples de bonnes instructions :
- "Mettre l'oignon coupé en deux dans le bol, puis mixer 5 sec / vitesse 5. Racler les parois du bol avec la spatule."
- "Ajouter l'huile d'olive et faire revenir 3 min / 120°C / sens inverse 🔄 / vitesse 1."

## Processus de travail

1. Quand l'utilisateur te donne un lien de recette, utilise l'outil `scrape_recipe` pour récupérer les détails
2. Analyse la recette et ADAPTE-LA pour le Thermomix avec les instructions appropriées
3. Montre la recette adaptée à l'utilisateur et demande confirmation
4. Une fois approuvé, utilise `upload_recipe` pour publier sur Cookidoo

IMPORTANT : Tu dois TOUJOURS adapter les étapes pour le Thermomix, pas juste copier les étapes originales !"""


def get_gemini_tools():
    """Create Gemini function declarations."""
    scrape_recipe = FunctionDeclaration(
        name="scrape_recipe",
        description="Récupère les détails d'une recette depuis n'importe quel site web (Marmiton, Cuisineaz, etc.)",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "L'URL de la recette à récupérer"
                }
            },
            "required": ["url"]
        }
    )
    
    upload_recipe = FunctionDeclaration(
        name="upload_recipe",
        description="Publie une recette personnalisée sur Cookidoo. N'utiliser qu'après confirmation de l'utilisateur.",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Nom de la recette"
                },
                "ingredients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Liste des ingrédients avec quantités"
                },
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Étapes de préparation adaptées au Thermomix"
                },
                "servings": {
                    "type": "integer",
                    "description": "Nombre de portions (défaut: 4)"
                },
                "prep_time": {
                    "type": "integer",
                    "description": "Temps de préparation en minutes (défaut: 30)"
                },
                "total_time": {
                    "type": "integer",
                    "description": "Temps total en minutes (défaut: 60)"
                }
            },
            "required": ["name", "ingredients", "steps"]
        }
    )
    
    return Tool(function_declarations=[scrape_recipe, upload_recipe])


def execute_function_call(function_name: str, function_args: dict) -> str:
    """Execute a function call from Gemini."""
    if function_name == "scrape_recipe":
        result = scrape_recipe_from_url(function_args.get("url", ""))
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    elif function_name == "upload_recipe":
        result = asyncio.run(upload_to_cookidoo(
            name=function_args.get("name", "Recipe"),
            ingredients=function_args.get("ingredients", []),
            steps=function_args.get("steps", []),
            servings=function_args.get("servings", 4),
            prep_time=function_args.get("prep_time", 30),
            total_time=function_args.get("total_time", 60),
            hints=function_args.get("hints")
        ))
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    return json.dumps({"error": f"Unknown function: {function_name}"})


def check_password() -> bool:
    """Check if the user has entered the correct password."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    
    if st.session_state.authenticated:
        return True
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("# 🍳 Cookidoo Recipe Creator")
        st.markdown("<p style='text-align: center; color: #b0b0b0;'>AI-powered Thermomix recipe creator</p>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter your password...",
            label_visibility="collapsed"
        )
        
        if st.button("🚀 Enter", use_container_width=True):
            if password == st.secrets.get("app_password", ""):
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Incorrect password")
    
    return False


def process_with_gemini(user_message: str, chat_history: list) -> tuple[str, list]:
    """Process a message with Gemini and handle function calls."""
    
    genai.configure(api_key=st.secrets["gemini_api_key"])
    
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        tools=[get_gemini_tools()],
        system_instruction=SYSTEM_PROMPT
    )
    
    # Build conversation history for Gemini
    gemini_history = []
    for msg in chat_history:
        role = "user" if msg["role"] == "user" else "model"
        gemini_history.append({"role": role, "parts": [msg["content"]]})
    
    chat = model.start_chat(history=gemini_history)
    
    response = chat.send_message(user_message)
    
    # Process function calls
    function_outputs = []
    max_iterations = 5
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        # Check for function calls
        if not response.candidates:
            break
            
        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            break
        
        function_call = None
        for part in candidate.content.parts:
            if hasattr(part, 'function_call') and part.function_call.name:
                function_call = part.function_call
                break
        
        if not function_call:
            break
        
        # Execute function
        function_name = function_call.name
        function_args = dict(function_call.args) if function_call.args else {}
        
        function_outputs.append(f"🔧 Executing `{function_name}`...")
        result = execute_function_call(function_name, function_args)
        function_outputs.append(f"✅ Done!")
        
        # Send function result back
        response = chat.send_message(
            genai.protos.Content(
                parts=[genai.protos.Part(
                    function_response=genai.protos.FunctionResponse(
                        name=function_name,
                        response={"result": result}
                    )
                )]
            )
        )
    
    # Get final text
    final_text = ""
    try:
        final_text = response.text
    except:
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    final_text += part.text
    
    if not final_text:
        final_text = "J'ai terminé l'action demandée."
    
    return final_text, function_outputs


def main_app():
    """Main chat application."""
    
    # Header
    st.markdown("# 🍳 Cookidoo Recipe Creator")
    st.markdown("<p style='text-align: center; color: #b0b0b0; margin-top: -1rem;'>Chat with AI to create Thermomix recipes</p>", unsafe_allow_html=True)
    
    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []
    
    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # Chat input
    if prompt := st.chat_input("Paste a recipe URL or describe what you want to cook..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Get AI response
        with st.chat_message("assistant"):
            with st.spinner("🤖 Thinking..."):
                try:
                    # Get chat history (excluding current message)
                    history = st.session_state.messages[:-1]
                    
                    # Process with Gemini
                    response_text, function_logs = process_with_gemini(prompt, history)
                    
                    # Show function execution logs
                    for log in function_logs:
                        if log.startswith("🔧"):
                            st.info(log)
                        else:
                            st.success(log)
                    
                    # Show response
                    st.markdown(response_text)
                    st.session_state.messages.append({"role": "assistant", "content": response_text})
                    
                except Exception as e:
                    error_msg = f"❌ Error: {str(e)}"
                    st.error(error_msg)
                    import traceback
                    st.code(traceback.format_exc())
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 💡 How to use")
        st.markdown("""
        1. Paste a recipe URL from any site
        2. AI will adapt it for Thermomix
        3. Review and say "OK" to approve
        4. Recipe uploads to Cookidoo!
        """)
        
        st.markdown("---")
        
        if st.button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()


# Main entry point
if __name__ == "__main__":
    if check_password():
        main_app()
