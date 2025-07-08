# app.py
import streamlit as st
from st_supabase_connection import SupabaseConnection
import hashlib
import pandas as pd
import requests
import urllib.parse


st.set_page_config(page_title="AI Prompt Hub", layout="wide")

def hash_password(password):
    """Hashes a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

conn = st.connection("supabase", type=SupabaseConnection)

try:
    SLACK_CLIENT_ID = st.secrets["SLACK_CLIENT_ID"]
    SLACK_CLIENT_SECRET = st.secrets["SLACK_CLIENT_SECRET"]
    REDIRECT_URI = st.secrets["REDIRECT_URI"]
    SLACK_SCOPES = "identity.basic,identity.email"
except KeyError:
    st.error("Slack credentials are not configured in Streamlit secrets.")
    st.stop()
    

slack_auth_url_params = {
    "user_scope": SLACK_SCOPES,
    "client_id": SLACK_CLIENT_ID,
    "redirect_uri": REDIRECT_URI,
}
slack_auth_url = f"https://slack.com/oauth/v2/authorize?{urllib.parse.urlencode(slack_auth_url_params)}"

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""
    st.session_state.user_id = 0
    st.session_state.role = ""


with st.sidebar:
    st.title("User Hub")

    query_params = st.query_params
    if "code" in query_params and not st.session_state.logged_in:
        code = query_params["code"]
        token_url = "https://slack.com/api/oauth.v2.access"
        response = requests.post(token_url, data={
            "client_id": SLACK_CLIENT_ID, "client_secret": SLACK_CLIENT_SECRET,
            "code": code, "redirect_uri": REDIRECT_URI
        })
        token_data = response.json()
        
        if token_data.get("ok"):
            user_identity = token_data.get("authed_user", {})
            st.session_state.logged_in = True
            st.session_state.username = user_identity.get("name", "Slack User")
            st.session_state.user_id = user_identity.get("id")
            st.session_state.role = "user"
            st.query_params.clear()
            st.rerun()
        else:
            st.error(f"Slack login failed: {token_data.get('error', 'Unknown')}")
    if st.session_state.logged_in:
        st.success(f"Logged in as **{st.session_state.username}**")
        st.write(f"Role: **{st.session_state.role.capitalize()}**")
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state.user_id = ""
            st.session_state.role = ""
            st.query_params.clear()
            st.rerun()

    else:
        member_tab, admin_tab = st.tabs(["Member Login", "Admin Login"])

        with member_tab:
            st.write("Login with your MDPlus Slack account.")
            st.link_button("Login with Slack", slack_auth_url, use_container_width=True, type="primary")

        with admin_tab:
            st.write("For administrative access only.")
            with st.form("admin_login_form"):
                username = st.text_input("Admin Username")
                password = st.text_input("Admin Password", type="password")
                login_button = st.form_submit_button("Login as Admin")

                if login_button:
                    password_hash = hash_password(password)
                    user_data = conn.client.table("users").select("*", count="exact").eq("username", username).eq("password_hash", password_hash).eq("role", "admin").execute()
                    
                    if user_data.count > 0:
                        user = user_data.data[0]
                        st.session_state.logged_in = True
                        st.session_state.username = user['username']
                        st.session_state.user_id = user['id']
                        st.session_state.role = user['role']
                        st.rerun()
                    else:
                        st.error("Invalid admin credentials or not an admin.")


st.image("logo.png", width=250)
st.title("AI Prompt Library")
st.markdown("Discover, share, and vote on the best AI prompts.")

tab_view, tab_submit, tab_admin = st.tabs(["View Prompts", "Submit a Prompt", "Admin Panel"])


with tab_view:
    st.header("Approved Community Prompts")
    prompts_data = conn.client.rpc('get_approved_prompts_with_username', {}).execute().data
    
    if not prompts_data:
        st.info("No prompts have been approved yet. Check back later!")
    else:
        prompts_df = pd.DataFrame(prompts_data)
        
        def calculate_avg_rating(prompt_id):
            rating_data = conn.client.table("votes").select("rating", count="exact").eq("prompt_id", prompt_id).execute()
            if rating_data.count > 0:
                return sum(r['rating'] for r in rating_data.data) / rating_data.count
            return 0
        
        prompts_df['avg_rating'] = prompts_df['id'].apply(calculate_avg_rating)
        
        prompts_df = prompts_df.sort_values(by='avg_rating', ascending=False).reset_index(drop=True)
        
        st.subheader("Search and Filter")
        
        search_query = st.text_input("Search by keyword in title or prompt text", placeholder="e.g., cardiology, exam, note")
        
        all_tags = set()
        for t in prompts_df['tags'].dropna():
            all_tags.update([tag.strip() for tag in t.split(',')])
        sorted_tags = sorted(list(all_tags))
        
        selected_tags = st.multiselect("Filter by tags", options=sorted_tags)

        filtered_df = prompts_df.copy() 

        if search_query:
            filtered_df = filtered_df[
                filtered_df['title'].str.contains(search_query, case=False, na=False) |
                filtered_df['prompt_text'].str.contains(search_query, case=False, na=False)
            ]

        if selected_tags:
            for tag in selected_tags:
                filtered_df = filtered_df[filtered_df['tags'].str.contains(tag, case=False, na=False)]

        st.markdown(f"---")
        st.write(f"**{len(filtered_df)} prompts found**")

        if filtered_df.empty:
            st.warning("No prompts match your current search criteria.")
        else:
            for index, row in filtered_df.iterrows():
                with st.expander(f"**{row['title']}** (Category: {row['category']})", expanded=False):
                    st.markdown(f"*Submitted by: {row['username']}*")
                    if row['tags']:
                        st.markdown(f"**Tags:** `{row['tags']}`")
                    st.code(row['prompt_text'], language="text")

                    col1, col2 = st.columns([1, 2])
                    with col1:
                        rating_data = conn.client.table("votes").select("rating", count="exact").eq("prompt_id", row['id']).execute()
                        avg_rating = sum(r['rating'] for r in rating_data.data) / rating_data.count if rating_data.count > 0 else 0
                        st.markdown(f"**Rating: {avg_rating:.2f} / 5** ({rating_data.count} votes)")

                    with col2:
                        if st.session_state.logged_in:
                            user_vote_data = conn.client.table("votes").select("rating").eq("prompt_id", row['id']).eq("user_id", st.session_state.user_id).execute().data
                            user_vote = user_vote_data[0]['rating'] if user_vote_data else 0
                            
                            star_cols = st.columns(5)
                            for i, star_col in enumerate(star_cols, 1):
                                with star_col:
                                    if st.button("⭐" if i <= user_vote else "☆", key=f"star_{row['id']}_{i}", use_container_width=True):
                                        new_rating = i
                                        if new_rating == user_vote: new_rating = 0
                                        
                                        conn.client.table("votes").upsert({
                                            "prompt_id": row['id'],
                                            "user_id": st.session_state.user_id,
                                            "rating": new_rating
                                        }).execute()
                                        st.rerun()
                        else:
                            st.warning("Login to vote!")

with tab_submit:
    st.header("Share Your Own Prompt")
    if st.session_state.logged_in:
        tag_options = {
            "Preclinical Students": [
                "Anatomy Helper",
                "Concept Instruction",
                "USMLE Step1",
                "Mnemonic Generator",
                "Case Simulator (Pre-Clinical)"
            ],
            "Clinical Students": [
                "Case Simulator (Clinical)",
                "Clinical Translation",
                "USMLE Step2",
                "Note Taker",
                "Scribing",
                "Clerkship Prep",
            ],
            "Residents": [
                "Case Simulator (Resident)",
                "USMLE Step3",
                "Fellowship Coach",
                "Guideline Check",
                "ICD-10 Helper",
            ],
            "Miscellaneous": []
        }
        category = st.selectbox(
            "Step 1: Select the category for your prompt",
            ["Preclinical Students", "Clinical Students", "Residents", "Miscellaneous"],
            key="category_selector" 
        )
        
        with st.form("prompt_submission_form", clear_on_submit=True):
            st.info("ℹ️ All fields are required. Please select or enter at least one tag to submit.")
            
            title = st.text_input("Prompt Title")
            
            selected_tags = []
            if category and category != "Miscellaneous":
                st.write("Step 2: Select relevant tags")
                selected_tags = st.multiselect(
                    "Select Tags (What does this prompt do?)", 
                    options=sorted(tag_options[category])
                )
            
            custom_tags_input = st.text_input("Or add your own custom tags (comma-separated)")

            prompt_text = st.text_area("Prompt Text", height=200)
            submitted = st.form_submit_button("Submit for Approval")

            if submitted:
                custom_tags = [tag.strip() for tag in custom_tags_input.split(',') if tag.strip()]
                all_tags = sorted(list(set(selected_tags + custom_tags)))

                if title and prompt_text and category and all_tags:
                    tags_string = ", ".join(all_tags)
                    
                    conn.client.table("prompts").insert({
                        "title": title,
                        "prompt_text": prompt_text,
                        "category": category,
                        "tags": tags_string,
                        "submitted_by_id": st.session_state.user_id,
                        "username": st.session_state.username,
                        "status": "pending"
                    }).execute()
                    st.success("Your prompt has been submitted for admin approval. Thank you!")
                else:
                    st.warning("Please fill out all fields, including at least one tag.")
    else:
        st.warning("You must be logged in to submit a prompt.")
        
        

with tab_admin:
    if st.session_state.role == 'admin':
        st.header("Admin Approval Queue")
        pending_prompts_data = conn.client.rpc('get_pending_prompts_with_username', {}).execute().data

        if not pending_prompts_data:
            st.info("No prompts are currently awaiting approval.")
        else:
            pending_df = pd.DataFrame(pending_prompts_data)
            for index, row in pending_df.iterrows():
                with st.container(border=True):
                    st.subheader(f"'{row['title']}' by {row['username']}")
                    st.markdown(f"**Category:** {row['category']}")
                    if row['tags']:
                        st.markdown(f"**Tags:** `{row['tags']}`")
                    st.code(row['prompt_text'], language='text')

                    col1, col2, col3 = st.columns([1, 1, 5])
                    with col1:
                        if st.button("Approve", key=f"approve_{row['id']}", type="primary"):
                            conn.client.table("prompts").update({"status": "approved"}).eq("id", row['id']).execute()
                            st.rerun()
                    with col2:
                        if st.button("Reject", key=f"reject_{row['id']}"):
                            conn.client.table("prompts").update({"status": "rejected"}).eq("id", row['id']).execute()
                            st.rerun()
    else:
        st.error("You do not have permission to view this page.")