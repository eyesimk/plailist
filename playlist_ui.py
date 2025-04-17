import streamlit as st
import pandas as pd
import subprocess
import re
import json
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import pandas as pd
import re  


# Load song table
master_song_table = pd.read_csv('final_song_table.csv')


auth_manager = SpotifyOAuth(
    client_id="**",   
    client_secret="**",  
    redirect_uri="**",
    scope="user-library-read playlist-modify-public",
    cache_path=".spotify_cache"
)

sp = spotipy.Spotify(auth_manager=auth_manager)

# --- Functions ---
def generate_playlist_query_prompt(conversation: list) -> str:
    system_prompt = """
You are a playlist assistant. Your job is to help users find music based on their mood, energy, or any vibe they want.

Make sure to be friendly, conversational, and engaging. If the user’s request is unclear, kindly ask for clarification.

Do not be overly formal, and try to make the conversation feel more natural.

Only use the supported features.

Ask at most two questions to clarify.

When you understand the request, only respond with the following JSON format. No more questions needed.

{
  "filter": {
    "FEATURE_NAME": "operator + value"
  },
  "sort": {
    "FEATURE_NAME": "ascending|descending"
  }
}

Supported features:
- BPM (beats per minute)
- Energy (0.0 to 100.0)
- Dance (0.0 to 100.0)
- Loud (in dB)
- Valence (0.0 to 100.0)
- Acoustic (0.0 to 100.0)

Examples of how to express a friendly, informal tone:
- "Got it! Let me pull up some tunes with a chill vibe for you."
- "Let’s dive into some upbeat energy, shall we?"
- "I hear you! Let me find some acoustic tracks with a relaxed mood."

Remember, keep it casual and fun!


Examples:
"I want calm music that builds energy"
{
  "filter": {
    "Energy": "< 44.0",
    "Valence": "< 53.0",
    "Acoustic": "> 66.0",
    "Dance": "> 70.0"
  },
  "sort": {
    "BPM": "ascending"
  },
  "response": "I've got some super chill vibes with a slow build-up in energy for you. Let’s go with something mellow that gets you moving, just a bit!"
}
Now generate a response based on the user request below.
"""
    full_convo = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in conversation])
    return f"{system_prompt}\n\nConversation so far:\n{full_convo}\n\nAssistant:"



def llama_chat(conversation: list) -> str:
    prompt = generate_playlist_query_prompt(conversation)
    try:
        result = subprocess.run(
            ["ollama", "run", "gemma3:4b"],
            input=prompt,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip() if result.stdout else ""
    except Exception as e:
        return f"Error: {e}"

def extract_json_from_text(text: str):
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {}
    return {}

def apply_filters_and_sort(df, parsed_json):
    filters = parsed_json.get("filter", {})
    sort = parsed_json.get("sort", {})

    for feature, condition in filters.items():
        if feature in df.columns:
            try:
                expression = f"`{feature}` {condition}"
                df = df.query(expression)
            except Exception as e:
                print(f"Error applying filter on {feature}: {e}")

    for feature, direction in sort.items():
        if feature in df.columns:
            ascending = direction == "ascending"
            df = df.sort_values(by=feature, ascending=ascending)

    return df

def get_track_id(track_name, artist_name):
    query = f"track:{track_name} artist:{artist_name}"
    results = sp.search(q=query, type='track', limit=1)
    items = results['tracks']['items']
    if items:
        return items[0]['id']
    return None


def is_pure_json_code_block(content):
    """Return True if message is just a ```json ... ``` block with valid JSON inside."""
    content = content.strip()
    if content.startswith("```json") and content.endswith("```"):
        try:
            json_str = re.search(r"```json\s*(\{.*\})\s*```", content, re.DOTALL).group(1)
            json.loads(json_str)
            return True
        except:
            return False
    return False

def create_playlist_and_add_tracks(df, name="Custom Generated Playlist"):
    track_ids = []
    for _, row in df.iterrows():
        track_id = get_track_id(row['Title'], row['Artist'])
        if track_id:
            track_ids.append(track_id)

    if not track_ids:
        return None

    user_id = sp.current_user()['id']
    playlist = sp.user_playlist_create(user=user_id, name=name)
    sp.playlist_add_items(playlist_id=playlist['id'], items=track_ids)
    return playlist['external_urls']['spotify']



import streamlit as st


st.markdown("""
    <style>
    .chat-assistant {
        color: #1DB954;  /* Spotify green */
        font-weight: bold;
    }
    .chat-msg {
        margin-left: 10px;
        margin-bottom: 1rem;
    }
    </style>
""", unsafe_allow_html=True)


# Streamlit UI
st.title("Talk to your plailist")

if "conversation" not in st.session_state:
    st.session_state.conversation = []
if "state" not in st.session_state:
    st.session_state.state = "INIT"

# State machine conversion to streamlit

if st.session_state.state == "INIT":
    user_input = st.text_input("🎧 You:", key="init_input")
    if user_input:
        st.session_state.conversation.append({"role": "user", "content": user_input})
        st.session_state.state = "WAITING_FOR_RESPONSE"
        st.rerun()

elif st.session_state.state == "WAITING_FOR_RESPONSE":
    response = llama_chat(st.session_state.conversation)
    st.session_state.conversation.append({"role": "assistant", "content": response})

    if "filter" in response and "sort" in response:
        st.session_state.state = "FINAL_JSON_READY"
    else:
        st.session_state.state = "ASKING_CLARIFICATION"
    st.rerun()

elif st.session_state.state == "ASKING_CLARIFICATION":
    clarification = st.text_input("You:", key="clarify_input")
    if clarification:
        st.session_state.conversation.append({"role": "user", "content": clarification})
        st.session_state.state = "WAITING_FOR_RESPONSE"
        st.rerun()

elif st.session_state.state == "FINAL_JSON_READY":
    filters = extract_json_from_text(st.session_state.conversation[-1]["content"])
    with st.expander("Filters"):
        st.code(json.dumps(filters, indent=2), language="json")

    df_filtered = apply_filters_and_sort(master_song_table.copy(), filters)
    st.session_state.final_df = df_filtered

    if st.button("Create Playlist on Spotify"):
        playlist_url = create_playlist_and_add_tracks(df_filtered)
        if playlist_url:
            st.success("Playlist created successfully!")
            st.markdown(f"[Open Playlist on Spotify]({playlist_url})")
        else:
            st.error("Could not create playlist. No valid track IDs found.")



#hide json responses-will be displayed in a seperate chunk

for message in st.session_state.conversation:
    content = message["content"].strip()

    if message["role"] == "assistant":
        if is_pure_json_code_block(content):
            continue

        st.markdown(
            f"<div class='chat-assistant'>Assistant:</div><div class='chat-msg'>{content}</div>",
            unsafe_allow_html=True
        )
    elif message["role"] == "user":
        st.markdown(
            f"<div><strong>You:</strong></div><div class='chat-msg'>{content}</div>",
            unsafe_allow_html=True
        )

# display dataframe at the end
if "final_df" in st.session_state:
    st.subheader("Here is your playlist:")
    st.dataframe(st.session_state.final_df)

