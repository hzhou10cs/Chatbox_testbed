import argparse
import os
import sys

import gradio as gr
from agents.chat import chat_agent
from agents.extractor import extractor_agent
from storage import ensure_base_dir
from logic.logic_user import (
    login_action,
    show_register_panel,
    back_to_login_panel,
    register_action,
    logout_action,
    load_profile_action,
    profile_edit_toggle,
)
from logic.logic_progress import load_progress_action, save_progress_action
from logic.logic_chat import (
    start_new_chat_action,
    continue_chat_action,
    end_chat_action,
    chat_send_action,
    refresh_history_list_action,
    load_history_conversation_action,
)
from logic.logic_goals import load_goal_summary_for_ui, save_goal_feedback_action

from dash_board import DASHBOARD_TXT

_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--mode", type=str, default=None)
_args, _unknown = _parser.parse_known_args(sys.argv[1:])
if _args.mode is not None:
    os.environ["SYSTEM_MODE"] = _args.mode


def switch_page(page_name: str):
    """Return visibility updates for all main pages based on the active page name."""
    return (
        gr.update(visible=(page_name == "dashboard")),
        gr.update(visible=(page_name == "profile")),
        gr.update(visible=(page_name == "progress")),
        gr.update(visible=(page_name == "chat")),
        gr.update(visible=(page_name == "history")),
        gr.update(visible=(page_name == "goals")),
    )


ensure_base_dir()

with gr.Blocks(title="LLM Agent for Rural Health") as demo:
    # Global states
    user_state = gr.State({"logged_in": False, "username": None})
    user_info_state = gr.State({})
    chat_history_state = gr.State([])  # [(user, bot)]
    chat_meta_state = gr.State(
        {"active": False, "date": None, "index": None, "finished": True, "username": None}
    )
    profile_edit_state = gr.State(False)

    # ========== Login panel ==========
    with gr.Column(visible=True) as login_panel:
        gr.Markdown("## 🧬 Health Assistant Login")
        login_username = gr.Textbox(label="Username")
        login_password = gr.Textbox(label="Password", type="password")
        login_button = gr.Button("Log in")
        go_register_button = gr.Button("Register new user")
        login_info = gr.Markdown("Please log in or register a new user.")

    # ========== Register panel ==========
    with gr.Column(visible=False) as register_panel:
        gr.Markdown("## 🧬 Register new user")
        reg_username = gr.Textbox(label="Login username (required)")
        reg_password = gr.Textbox(label="Password (required)", type="password")
        reg_password2 = gr.Textbox(label="Confirm password (required)", type="password")

        gr.Markdown("### Basic information")
        reg_first_name = gr.Textbox(label="First name")
        reg_last_name = gr.Textbox(label="Last name")
        reg_gender = gr.Dropdown(
            label="Gender",
            choices=["Male", "Female", "Other", "Prefer not to say"],
        )
        reg_occupation = gr.Textbox(label="Occupation (optional)")
        reg_phone = gr.Textbox(label="Phone")
        reg_email = gr.Textbox(label="Email")

        gr.Markdown("### Health baseline")
        reg_height = gr.Textbox(label="Height (unit up to you)")
        reg_initial_weight = gr.Textbox(
            label="Initial weight (unit up to you)"
        )
        reg_body_measurements = gr.Textbox(
            label="Body measurements (optional, e.g., 88-66-90)"
        )

        reg_weight_statement = gr.Textbox(
            label="Personal weight loss statement (optional)", lines=3
        )

        gr.Markdown("### Health history (use N/A if unknown)")
        reg_allergy = gr.Textbox(label="Allergies", value="N/A")
        reg_medication = gr.Textbox(label="Medication", value="N/A")
        reg_lifestyle = gr.Textbox(label="Lifestyle", value="N/A")
        reg_medical_history = gr.Textbox(
            label="Past medical history ", value="N/A"
        )

        register_button = gr.Button("Submit registration")
        back_login_button = gr.Button("Back to login")
        register_info = gr.Markdown("")

    # ========== Main panel ==========
    with gr.Row(visible=False) as main_panel:
        # Left navigation
        with gr.Column(scale=1, min_width=180):
            gr.Markdown("### Navigation")
            btn_dashboard = gr.Button("📊 Dashboard")
            btn_profile = gr.Button("👤 Profile")
            btn_progress = gr.Button("📈 Progress input")
            btn_chat = gr.Button("💬 Agent chat")
            btn_history = gr.Button("🕓 Chat history")
            btn_goals = gr.Button("🎯 Current goals")
            gr.Markdown("---")
            logout_btn = gr.Button("Log out", variant="secondary")

        # Right content
        with gr.Column(scale=4) as main_content:
            # Dashboard
            with gr.Column(visible=True) as page_dashboard:
                gr.Markdown(DASHBOARD_TXT)

            # Profile
            with gr.Column(visible=False) as page_profile:
                gr.Markdown("## 👤 User profile")
                profile_status = gr.Markdown(
                    "Profile will be loaded automatically when you open this page."
                )

                with gr.Row():
                    profile_photo = gr.Image(
                        label="User photo (optional)",
                        type="filepath",
                        interactive=False,
                    )
                    profile_photo_upload = gr.File(
                        label="Upload photo file (PNG/JPG, optional)",
                        file_types=["image"],
                        interactive=False,
                    )

                with gr.Row():
                    profile_first_name = gr.Textbox(
                        label="First name (required)", interactive=False
                    )
                    profile_last_name = gr.Textbox(
                        label="Last name (required)", interactive=False
                    )

                with gr.Row():
                    profile_gender = gr.Dropdown(
                        label="Gender (required)",
                        choices=[
                            "Male",
                            "Female",
                            "Other",
                            "Prefer not to say",
                        ],
                        interactive=False,
                    )
                    profile_occupation = gr.Textbox(
                        label="Occupation (optional)", interactive=False
                    )

                with gr.Row():
                    profile_phone = gr.Textbox(
                        label="Phone (required)", interactive=False
                    )
                    profile_email = gr.Textbox(
                        label="Email (required)", interactive=False
                    )

                gr.Markdown("### Health baseline")
                with gr.Row():
                    profile_height = gr.Textbox(
                        label="Height (required)", interactive=False
                    )
                    profile_initial_weight = gr.Textbox(
                        label="Initial weight (required)", interactive=False
                    )
                    profile_body_measurements = gr.Textbox(
                        label="Body measurements (optional)",
                        interactive=False,
                    )

                profile_weight_statement = gr.Textbox(
                    label="Personal weight loss statement (optional)",
                    lines=3,
                    interactive=False,
                )

                gr.Markdown("### Health history (use N/A if unknown)")
                profile_allergy = gr.Textbox(
                    label="Allergies (required)", interactive=False
                )
                profile_medication = gr.Textbox(
                    label="Medication (required)", interactive=False
                )
                profile_lifestyle = gr.Textbox(
                    label="Lifestyle (required)", interactive=False
                )
                profile_medical_history = gr.Textbox(
                    label="Past medical history (required)", interactive=False
                )

                profile_register_date = gr.Textbox(
                    label="Registration date (auto recorded)", interactive=False
                )

                profile_edit_btn = gr.Button("Edit personal information")

            # Progress
            with gr.Column(visible=False) as page_progress:
                gr.Markdown("## 📈 Progress input")
                with gr.Row():
                    week_input = gr.Dropdown(
                        label="Week number",
                        choices=[str(i) for i in range(1, 53)],
                        value="1",
                    )
                    day_input = gr.Dropdown(
                        label="Day number (1 = first day of week)",
                        choices=[str(i) for i in range(1, 8)],
                        value="1",
                    )
                load_progress_btn = gr.Button(
                    "Load or create record"
                )
                progress_date = gr.Textbox(label="Absolute date", interactive=False)
                weight_today = gr.Textbox(label="Weight today (optional)")
                progress_notes = gr.Textbox(
                    label="Notes for today (free text)", lines=5
                )
                save_progress_btn = gr.Button("Save progress")
                progress_status = gr.Markdown("")

            # Chat
            with gr.Column(visible=False) as page_chat:
                gr.Markdown("## 💬 Agent chat")
                with gr.Row():
                    start_new_chat_btn = gr.Button("Start new conversation")
                    continue_chat_btn = gr.Button(
                        "Continue unfinished conversation"
                    )

                end_chat_btn = gr.Button(
                    "End current conversation", visible=False
                )

                chatbot = gr.Chatbot(
                    label="Current conversation",
                    type="tuples",
                    visible=False,
                )
                chat_input = gr.Textbox(
                    label="Your message", lines=2, visible=False
                )
                chat_status = gr.Markdown("", visible=False)
                chat_send_btn = gr.Button("Send", visible=False)
                
                system_prompt_box = gr.Textbox(
                    label="Current system prompt (for debugging only)",
                    lines=12,
                    interactive=False,
                    visible=True,
                )
                message_sent_box = gr.Textbox(
                    label="Last message payload (for debugging only)",
                    lines=12,
                    interactive=False,
                    visible=True,
                )
                cst_box = gr.Textbox(
                    label="Current CST (for debugging only)",
                    lines=12,
                    interactive=False,
                    visible=True,
                )

            # History
            with gr.Column(visible=False) as page_history:
                gr.Markdown("## 🕓 Chat history")
                refresh_history_btn = gr.Button("Refresh conversation list")
                history_dropdown = gr.Dropdown(label="Select a conversation")
                history_status = gr.Markdown("")
                history_chatbot = gr.Chatbot(
                    label="Selected conversation", type="tuples"
                )

            # Goals
            with gr.Column(visible=False) as page_goals:
                gr.Markdown("## 🎯 Current goals")
                goal_date_label = gr.Markdown("Date:")
                goal_summary = gr.Textbox(
                    label="LLM-generated goal summary",
                    lines=6,
                    interactive=False,
                )
                goal_feedback = gr.Textbox(
                    label=(
                        "Your feedback on the goal "
                        "(will be used as future prompt context)"
                    ),
                    lines=4,
                )
                with gr.Row():
                    load_goal_btn = gr.Button("Load / generate latest goal")
                    save_goal_btn = gr.Button("Submit feedback")
                goal_status = gr.Markdown("")

    # ====== Event bindings ======

    # Login / register
    login_button.click(
        login_action,
        inputs=[login_username, login_password, user_state, user_info_state],
        outputs=[
            login_info,
            user_state,
            user_info_state,
            login_panel,
            register_panel,
            main_panel,
        ],
    )

    go_register_button.click(
        show_register_panel,
        inputs=None,
        outputs=[login_panel, register_panel],
    )

    back_login_button.click(
        back_to_login_panel,
        inputs=None,
        outputs=[login_panel, register_panel],
    )

    register_button.click(
        register_action,
        inputs=[
            reg_username,
            reg_password,
            reg_password2,
            reg_first_name,
            reg_last_name,
            reg_gender,
            reg_occupation,
            reg_phone,
            reg_email,
            reg_height,
            reg_initial_weight,
            reg_body_measurements,
            reg_weight_statement,
            reg_allergy,
            reg_medication,
            reg_lifestyle,
            reg_medical_history,
            user_state,
            user_info_state,
        ],
        outputs=[
            register_info,
            user_state,
            user_info_state,
            login_panel,
            register_panel,
            main_panel,
        ],
    )

    # Logout
    logout_btn.click(
        logout_action,
        inputs=[user_state, user_info_state, chat_history_state, chat_meta_state],
        outputs=[
            user_state,
            user_info_state,
            chat_history_state,
            chat_meta_state,
            login_panel,
            register_panel,
            main_panel,
        ],
    )

    # Navigation
    btn_dashboard.click(
        lambda: switch_page("dashboard"),
        inputs=None,
        outputs=[
            page_dashboard,
            page_profile,
            page_progress,
            page_chat,
            page_history,
            page_goals,
        ],
    )

    btn_profile.click(
        lambda: switch_page("profile"),
        inputs=None,
        outputs=[
            page_dashboard,
            page_profile,
            page_progress,
            page_chat,
            page_history,
            page_goals,
        ],
    ).then(
        load_profile_action,
        inputs=[user_state, user_info_state],
        outputs=[
            profile_first_name,
            profile_last_name,
            profile_gender,
            profile_occupation,
            profile_phone,
            profile_email,
            profile_height,
            profile_initial_weight,
            profile_body_measurements,
            profile_weight_statement,
            profile_allergy,
            profile_medication,
            profile_lifestyle,
            profile_medical_history,
            profile_photo,
            profile_register_date,
            profile_status,
        ],
    )

    btn_progress.click(
        lambda: switch_page("progress"),
        inputs=None,
        outputs=[
            page_dashboard,
            page_profile,
            page_progress,
            page_chat,
            page_history,
            page_goals,
        ],
    )

    btn_chat.click(
        lambda: switch_page("chat"),
        inputs=None,
        outputs=[
            page_dashboard,
            page_profile,
            page_progress,
            page_chat,
            page_history,
            page_goals,
        ],
    )

    btn_history.click(
        lambda: switch_page("history"),
        inputs=None,
        outputs=[
            page_dashboard,
            page_profile,
            page_progress,
            page_chat,
            page_history,
            page_goals,
        ],
    )

    btn_goals.click(
        lambda: switch_page("goals"),
        inputs=None,
        outputs=[
            page_dashboard,
            page_profile,
            page_progress,
            page_chat,
            page_history,
            page_goals,
        ],
    ).then(
        load_goal_summary_for_ui,
        inputs=[user_state],
        outputs=[goal_summary, goal_feedback, goal_date_label, goal_status],
    )

    # Profile edit toggle
    profile_edit_btn.click(
        profile_edit_toggle,
        inputs=[
            profile_edit_state,
            profile_first_name,
            profile_last_name,
            profile_gender,
            profile_occupation,
            profile_phone,
            profile_email,
            profile_height,
            profile_initial_weight,
            profile_body_measurements,
            profile_weight_statement,
            profile_allergy,
            profile_medication,
            profile_lifestyle,
            profile_medical_history,
            profile_photo_upload,
            user_state,
            user_info_state,
        ],
        outputs=[
            profile_edit_state,
            profile_status,
            profile_first_name,
            profile_last_name,
            profile_gender,
            profile_occupation,
            profile_phone,
            profile_email,
            profile_height,
            profile_initial_weight,
            profile_body_measurements,
            profile_weight_statement,
            profile_allergy,
            profile_medication,
            profile_lifestyle,
            profile_medical_history,
            profile_register_date,
            profile_photo_upload,
            profile_edit_btn,
        ],
    )

    # Progress load/save
    load_progress_btn.click(
        load_progress_action,
        inputs=[week_input, day_input, user_state],
        outputs=[progress_date, weight_today, progress_notes, progress_status],
    )

    save_progress_btn.click(
        save_progress_action,
        inputs=[
            week_input,
            day_input,
            progress_date,
            weight_today,
            progress_notes,
            user_state,
        ],
        outputs=[progress_status],
    )

    # Chat: start / continue / end / send
    start_new_chat_btn.click(
        start_new_chat_action,
        inputs=[user_state, chat_history_state, chat_meta_state],
        outputs=[
            chat_history_state,
            chat_meta_state,
            chat_status,
            chatbot,
            chat_input,
            chat_send_btn,
            end_chat_btn,
        ],
    )

    continue_chat_btn.click(
        continue_chat_action,
        inputs=[user_state, chat_history_state, chat_meta_state],
        outputs=[
            chat_history_state,
            chat_meta_state,
            chat_status,
            chatbot,
            chat_input,
            chat_send_btn,
            end_chat_btn,
        ],
    )

    # dialogue end: call end_chat_action，then refresh summary/feedback in Goals 
    end_chat_btn.click(
        end_chat_action,
        inputs=[user_state, chat_history_state, chat_meta_state],
        outputs=[
            chat_meta_state,
            chat_status,
            chatbot,
            chat_input,
            chat_send_btn,
            end_chat_btn,
        ],
    ).then(
        load_goal_summary_for_ui,
        inputs=[user_state],
        outputs=[goal_summary, goal_feedback, goal_date_label, goal_status],
    )

    chat_send_btn.click(
        chat_send_action,
        inputs=[chat_input, chat_history_state, user_state, user_info_state, chat_meta_state],
        outputs=[chat_history_state, chat_status, chatbot, system_prompt_box, message_sent_box, cst_box],
    )

    # Chat history
    refresh_history_btn.click(
        refresh_history_list_action,
        inputs=[user_state],
        outputs=[history_dropdown, history_status],
    )

    history_dropdown.change(
        load_history_conversation_action,
        inputs=[user_state, history_dropdown],
        outputs=[history_chatbot, history_status],
    )

    # Goals: manually submit load / save
    load_goal_btn.click(
        load_goal_summary_for_ui,
        inputs=[user_state],
        outputs=[goal_summary, goal_feedback, goal_date_label, goal_status],
    )

    save_goal_btn.click(
        save_goal_feedback_action,
        inputs=[user_state, goal_summary, goal_feedback, goal_date_label],
        outputs=[goal_status],
    )

if __name__ == "__main__":
    demo.launch()
