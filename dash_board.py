DASHBOARD_TXT = """
## 📊 Dashboard – Local LLM Health Coach

Welcome to the **Local LLM Health Assistant**.  
This dashboard is a quick guide to what the app can do, how to use the UI, and how the backend is wired.

---

### 🧭 What this app does (current version)

This app is a **12-week weight-loss coaching assistant** with:

- **User accounts & profiles**  
  Each user has a local account with basic contact info and health background.

- **Progress tracking over weeks & days**  
  You can log progress by week/day and revisit or edit entries later.

- **Dual-agent design: LLM-driven coaching agent**  
  A “coach” agent chats with the user using Motivational Interviewing + SMART goal style prompts.

- **Dual-agent design: Extractor / summarizer agent**  
  A second “extractor” agent summarizes recent conversations into structured JSON “goal summaries”.

- **Goal summary + user feedback**  
  The assistant’s goals + the user’s feedback are stored per date and fed back into future prompts.

- **Local, file-based storage**  
  No cloud database: everything lives under `user_data/` in simple JSON files and folders.

Right now the app can run in **UI test mode** (dummy replies) or connect to a **local vLLM server** for real model inference, depending on the configuration in `llm_config.py` / `llm_stub.py`.

---

### 🧑‍💻 How to use the UI

The main workflow is:

1. **Register → Login**
2. Fill or review your **profile**
3. Log your **weekly / daily progress**
4. Use **Agent chat** to talk with the coach
5. Check **Goal summary & feedback**
6. Browse **Chat history** for past conversations

Each item in the left sidebar opens a different page:

#### 1. Login / Register

- On startup you see the **login panel**:
  - Enter username + password.
  - On successful login, the app loads your data and switches to the main dashboard.

- Click **“Register”** to create a new account:
  - Choose a login username + password.
  - Fill in required profile fields (name, gender, contact info, basic health info, etc.).
  - On successful registration:
    - A folder is created: `user_data/<username>/`
    - Initial JSON files are created for your profile, progress, goals, and chats.
    - You are redirected to the **Dashboard**.

#### 2. Profile page

- Shows your **current profile** (loaded automatically when you open the page):
  - Photo (optional upload)
  - Name, gender, occupation
  - Phone, email
  - Height, initial weight, body measurements
  - Weight-loss statement & health history fields (allergies, medication, lifestyle, past medical history)

- **Edit flow**:
  - Click **“Edit profile”** to unlock the fields.
  - Modify the values.
  - Click **“Save profile”** to write changes back to your local JSON file.
  - After saving, fields become read-only again until you click “Edit” next time.

#### 3. Progress tracking page

- Designed for a **12-week program**:
  - Select **week number** and **day number** (e.g., Week 3, Day 2).
  - The app computes the corresponding **absolute date** based on your registration date.
  - If there is existing data for that day, it is automatically loaded into the form.
  - You can edit fields (e.g., weight, notes, daily observations).

- Click **“Save progress”** to update the JSON file for that user:
  - Progress is stored in a structured JSON, indexed by week/day and by actual date.
  - Re-selecting the same week/day will reload the saved entry.

#### 4. Agent Chat page

This is the main coaching interface.

- Initial state:
  - Only the control buttons are visible:
    - **“Start new conversation”**
    - **“Continue unfinished conversation”**
  - The chatbox, input field, and “End conversation” button are hidden to avoid accidental use.

- **Start new conversation**:
  - Creates a new conversation entry for `today` with an incremented session index (e.g., session 1, 2, 3…).
  - Marks the new conversation as **active** and not finished.
  - Shows:
    - Chat history box
    - Input textbox
    - “Send” button
    - “End current conversation” button

- **Continue unfinished conversation**:
  - Looks up the most recent **active** conversation for the current user.
  - Loads its history into the chatbox.
  - Re-enables the chat UI.

- **Send**:
  - Appends your user message to the active conversation.
  - Calls the **chat agent** (via `llm_reply_stub()` → vLLM or UI-test stub).
  - The agent builds a **system prompt** that includes:
    - Base coaching instructions (MI + SMART rules)
    - Your profile summary
    - Latest goal summary / feedback
  - The LLM reply is appended to the conversation history.
  - In parallel, the **extractor agent** reads:
    - Previous coach question (if any)
    - Your current answer
    - Current coach reply  
    and writes an updated **goal summary JSON** for that date.

- Below the send button, there is a **read-only “Current system prompt” box**:
  - Shows the *exact* system prompt used for this turn.
  - Useful for debugging prompt design and understanding what context the LLM sees.

- **End current conversation**:
  - Marks this conversation as finished in the index.
  - Saves the final history to disk (under `user_data/<username>/chats/…`).
  - Next time “Start new conversation” is clicked, the session index increments.

#### 5. Chat History page

- Provides a dropdown listing all saved conversations for the logged-in user:
  - Typically formatted as `YYYY-MM-DD | session_index`.
- When you select an item:
  - The full conversation history is loaded and displayed in the chat history component.
  - A status message indicates whether the conversation is **finished** or still **active**.

This page is **read-only**: it does not modify any files.

#### 6. Goal Summary page

- Automatically loads the **most recent goal summary** for the logged-in user:
  - The summary is produced by the extractor agent and stored in `goals.json`.
  - The summary is **read-only** and used as part of the system prompt in future chats.

- Below the summary, there is a **feedback** area:
  - You can type your reflections on how the goals went (e.g., “This week was hard because…”, “I want to shift focus to sleep.”).
  - When you click **“Save feedback”**:
    - The feedback is stored in `goals.json` under today’s date.
    - Future LLM calls read this feedback and incorporate it into the coaching context.

---

### 🧱 Application structure (high level)

The code is roughly organized as:

- **`app.py`**
  - Gradio UI layout and event wiring.
  - Manages pages (Dashboard / Profile / Progress / Chat / History / Goals).
  - Connects UI components to logic functions.

- **`logic/` package**
  - `logic_user.py`: login, registration, profile load/save, user state.
  - `logic_progress.py`: weekly/daily progress load/save.
  - `logic_chat.py`: conversation lifecycle (start/continue/end), history management, calls to chat agent & extractor, saving chat logs.
  - `logic_goals.py`: load/save goal summaries and feedback, expose “load latest goal for UI” and “save feedback”.

- **`agents/` package**
  - `chat.py`: main coach agent.
    - Builds the system prompt (MI + SMART + user profile + latest goals).
    - Formats messages for the OpenAI-style /v1/chat/completions API.
  - `extractor.py`: summarizer agent.
    - Reads recent conversation snippets.
    - Produces a **structured JSON** goal summary used by `logic_goals`.

- **`llm_stub.py`**
  - Wraps the LLM backend.
  - In **UI test mode**, returns deterministic dummy replies for fast UI iteration.
  - In **normal mode**, sends HTTP requests to a local vLLM server using an OpenAI-compatible API.

- **`prompt_chat.py` / `prompt_helper_*.py`**
  - Store the base coaching prompts (Prompt A) and the extractor’s extraction schemas (Prompt B).
  - Central place to tweak the behavior of both agents.

- **`storage.py`**
  - Handles paths and JSON utilities:
    - `ensure_base_dir()`
    - `get_user_dir(username)`
    - `get_user_file(username, filename)`
    - `load_json(path, default)`
    - `save_json(path, data)`
    - `today_str()` helper

---

### 📂 Data layout on disk

All persistent data is stored locally under a base directory, e.g.:

```text
user_data/
  <username>/
    profile.json         # registration + profile info
    progress.json        # weekly/daily progress entries
    goals.json           # goal summaries + user feedback, keyed by date
    chats/
      index.json         # overview of all conversations (date, index, finished)
      2025-11-26_1.json  # conversation files (metadata + turn-by-turn history)
      2025-11-26_2.json
    extractor/
      ...                # optional: per-date extractor outputs, if separated

"""