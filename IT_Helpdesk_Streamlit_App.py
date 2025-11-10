"""
Infinium Pharmachem Limited | IT Helpdesk - Enterprise Email Edition
---------------------------------------------------------------------
Final stable script:
- Submit tickets (User)
- IT Officer full access (view/assign/resolve/export)
- Future Updates + Contact Us working
- Email notifications on In Progress / Resolved
- No experimental_rerun usage
---------------------------------------------------------------------
"""

import traceback
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta
import io
import altair as alt
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from PIL import Image

# Options
st.set_option("client.showErrorDetails", True)
st.set_page_config(page_title="Infinium Pharmachem Limited | IT Helpdesk", layout="wide")

# Config
LOGO_FILE = "logo.png"  # not required; script will ignore if not present
DB_PATH = "tickets.db"
ADMIN_PASSWORD = "ipl123"

# Load .env
load_dotenv()
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or 587)
SMTP_USER = os.getenv("SMTP_USER") or ""
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or ""
FROM_EMAIL = os.getenv("FROM_EMAIL") or SMTP_USER
IT_RECIPIENTS = [x.strip() for x in os.getenv("IT_RECIPIENTS", "").split(",") if x.strip()]

# Database init
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id TEXT,
            employee_name TEXT,
            department TEXT,
            contact TEXT,
            identification TEXT,
            category TEXT,
            priority TEXT,
            description TEXT,
            attachment BLOB,
            attachment_name TEXT,
            status TEXT,
            assigned_to TEXT,
            raised_at TEXT,
            resolved_at TEXT,
            resolution_notes TEXT
        )
    """)
    conn.commit()
    return conn

conn = init_db()

# Helpers
def generate_ticket_id(conn):
    today = datetime.now().strftime("%Y-%m-%d")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tickets WHERE raised_at LIKE ?", (f"{today}%",))
    count = (c.fetchone()[0] if c.fetchone() is None else None)  # avoid double fetch
    # safer approach: fetch once
    c.execute("SELECT COUNT(*) FROM tickets WHERE raised_at LIKE ?", (f"{today}%",))
    row = c.fetchone()
    cnt = (row[0] if row else 0) + 1
    return f"{today}-{str(cnt).zfill(3)}"

def is_email(s):
    return isinstance(s, str) and ("@" in s) and ("." in s)

# Email function
def send_email(subject, ticket_info, to_list, cc=None):
    """
    Returns (ok:bool, err_msg or None)
    """
    try:
        if not SMTP_USER or not SMTP_PASSWORD:
            return False, "SMTP credentials not configured."

        msg = MIMEMultipart("alternative")
        msg["From"] = FROM_EMAIL
        msg["To"] = ", ".join(to_list)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject

        color = "#eab308" if ticket_info.get("status") == "In Progress" else "#16a34a"
        html = f"""
        <html><body style='font-family:Segoe UI,Arial,sans-serif;background:#f3f4f6;padding:20px;'>
        <div style='max-width:600px;margin:auto;background:#fff;border-radius:10px;overflow:hidden;'>
        <div style='background:#0f172a;color:#fff;padding:12px 20px;'>
        <b>Infinium IT Helpdesk</b>
        </div>
        <div style='padding:20px;color:#111827;'>
        <p>Dear <b>{ticket_info.get('employee_name','User')}</b>,</p>
        <p>Your ticket has been updated:</p>
        <table style='width:100%;border-collapse:collapse;margin:10px 0;'>
        <tr><td><b>Ticket ID:</b></td><td>{ticket_info.get('ticket_id','')}</td></tr>
        <tr><td><b>Status:</b></td><td style='color:{color};font-weight:bold'>{ticket_info.get('status','')}</td></tr>
        <tr><td><b>Category:</b></td><td>{ticket_info.get('category','')}</td></tr>
        <tr><td><b>Priority:</b></td><td>{ticket_info.get('priority','')}</td></tr>
        </table>
        <p><b>Description:</b><br>{ticket_info.get('description','')}</p>
        <p><b>Resolution Notes:</b><br>{ticket_info.get('resolution_notes','(Not provided)')}</p>
        <p>Regards,<br><b>Prince Prajapati</b><br>IT Officer – Infinium Pharmachem Limited</p>
        </div>
        </div></body></html>
        """
        msg.attach(MIMEText(html, "html", "utf-8"))

        # Build recipients list (To + Cc)
        recipients = list(to_list)
        if cc:
            recipients += list(cc)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(FROM_EMAIL, recipients, msg.as_string())

        return True, None
    except Exception as e:
        return False, str(e)

# Ticket DB operations
def add_ticket(data):
    c = conn.cursor()
    c.execute('''INSERT INTO tickets
                 (ticket_id, employee_name, department, contact, identification, category,
                  priority, description, attachment, attachment_name, status, assigned_to, raised_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (data["ticket_id"], data["employee_name"], data["department"], data["contact"],
               data.get("identification",""), data["category"], data["priority"],
               data["description"], data.get("attachment"), data.get("attachment_name"),
               "Open", "", datetime.now().isoformat()))
    conn.commit()

def fetch_tickets():
    c = conn.cursor()
    c.execute("SELECT * FROM tickets ORDER BY raised_at DESC")
    cols = [d[0] for d in c.description] if c.description else []
    rows = c.fetchall()
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)

def update_ticket(ticket_id, updates):
    c = conn.cursor()
    set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
    params = list(updates.values()) + [ticket_id]
    c.execute(f"UPDATE tickets SET {set_clause} WHERE ticket_id=?", params)
    conn.commit()

    # send email on status change to In Progress or Resolved
    if updates.get("status") in ["In Progress", "Resolved"]:
        c.execute("SELECT employee_name, contact, category, priority, description FROM tickets WHERE ticket_id=?", (ticket_id,))
        row = c.fetchone()
        if not row:
            return
        name, contact, category, priority, desc = row
        if is_email(contact):
            ticket_info = {
                "ticket_id": ticket_id,
                "employee_name": name,
                "status": updates["status"],
                "category": category,
                "priority": priority,
                "description": desc,
                "resolution_notes": updates.get("resolution_notes", "")
            }
            subject = f"[Ticket {ticket_id}] {updates['status']} - Infinium IT Helpdesk"
            ok, err = send_email(subject, ticket_info, [contact], cc=IT_RECIPIENTS)
            # show feedback
            if ok:
                st.info(f"📧 Email sent to {contact}")
            else:
                st.warning(f"⚠️ Email sending failed: {err}")

def df_to_excel_bytes(df):
    with io.BytesIO() as buffer:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Tickets")
        return buffer.getvalue()

# CSS
st.markdown("""
<style>
.header-title{font-size:28px;font-weight:700;color:#0f172a;}
.contact-card{background:linear-gradient(180deg,#ffffff,#f8fafc);
border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,0.05);padding:18px;}
.ticket-card{background:#fff;border-radius:10px;padding:14px;box-shadow:0 6px 14px rgba(11,22,39,0.06);margin-bottom:12px;}
</style>
""", unsafe_allow_html=True)

# Main app
def main():
    if "role" not in st.session_state:
        st.session_state.role = None

    # Sidebar
    with st.sidebar:
        st.markdown("### 🔐 Login Panel")
        if st.session_state.role is None:
            role = st.selectbox("Select Role", ["User", "IT Officer"], key="role_select")
            pwd = st.text_input("Access Key (IT Officer only)", type="password", key="pwd_input")
            if st.button("Login", key="login_btn"):
                if role == "IT Officer" and pwd == ADMIN_PASSWORD:
                    st.session_state.role = "IT Officer"
                    st.experimental_rerun()  # allowed method (rerun for refreshing UI)
                elif role == "User":
                    st.session_state.role = "User"
                    st.experimental_rerun()
                else:
                    st.error("Invalid credentials")
        else:
            st.write(f"Logged in as **{st.session_state.role}**")
            if st.button("Logout", key="logout_btn"):
                st.session_state.role = None
                st.experimental_rerun()

        st.markdown("---")
        if st.session_state.role == "User":
            page = st.selectbox("Navigate", ["Submit Ticket", "Future Updates", "Contact Us"], key="nav_user")
        else:
            page = st.selectbox("Navigate", ["Submit Ticket", "IT Officer Dashboard", "Reports & Export", "Future Updates", "Contact Us"], key="nav_officer")
        st.markdown("---")

    # Header
    st.markdown(f"<h1 class='header-title'>Infinium Pharmachem Limited | IT Helpdesk</h1>", unsafe_allow_html=True)
    st.markdown("<hr>", unsafe_allow_html=True)

    # Departments list
    DEPARTMENTS = [
        "Select...", "Accounts","HR","Purchase","CA/CS/CFO","Import/Export","Sales","DEO",
        "Production","Admin & Logistics","QA","QC","Micro","R&D","Engineering","Manufacturing"
    ]

    # Determine page from sidebar widget keys
    # (one of the two nav widgets exists; check st.session_state)
    if st.session_state.get("nav_user"):
        page = st.session_state["nav_user"]
    elif st.session_state.get("nav_officer"):
        page = st.session_state["nav_officer"]
    # else page variable is already set from earlier

    # Submit Ticket
    if page == "Submit Ticket":
        st.subheader("🎫 Raise a New Ticket")
        with st.form("ticket_form", clear_on_submit=True):
            col1, col2 = st.columns([2,1])
            with col1:
                employee_name = st.text_input("Your Name *", key="fname")
                department = st.selectbox("Department *", DEPARTMENTS, key="dept")
                contact = st.text_input("Contact (Email / Phone)", key="contact")
                identification = st.text_input("Employee ID (optional)", key="ident")
                category = st.selectbox("Issue Category *", ["Select...","Network","Printer","Email","Software","Hardware","Access","Other"], key="cat")
                priority = st.selectbox("Priority *", ["Select...","Low","Medium","High","Critical"], index=1, key="prio")
                description = st.text_area("Describe the Issue", height=140, key="desc")
            with col2:
                st.info("Attach screenshot or file (optional)")
                uploaded_file = st.file_uploader("Upload file", type=["png","jpg","jpeg","pdf","txt","log","xlsx","csv"], key="upl")
                file_bytes = uploaded_file.read() if uploaded_file else None

            submitted = st.form_submit_button("Submit Ticket")  
            if submitted:
                try:
                    if not employee_name or not employee_name.strip():
                        st.error("⚠️ Name is required.")
                    elif department == "Select...":
                        st.error("⚠️ Please select a department.")
                    elif category == "Select...":
                        st.error("⚠️ Please select an issue category.")
                    elif priority == "Select...":
                        st.error("⚠️ Please select a priority.")
                    else:
                        ticket_id = generate_ticket_id(conn)
                        data = {
                            "ticket_id": ticket_id,
                            "employee_name": employee_name.strip(),
                            "department": department,
                            "contact": contact.strip(),
                            "identification": identification.strip(),
                            "category": category,
                            "priority": priority,
                            "description": description.strip(),
                            "attachment": file_bytes,
                            "attachment_name": uploaded_file.name if uploaded_file else ""
                        }
                        add_ticket(data)
                        st.success(f"✅ Ticket {ticket_id} submitted successfully!")
                        st.balloons()
                except Exception as e:
                    st.error("❌ Ticket submission failed:")
                    st.code(traceback.format_exc())

    # IT Officer Dashboard
    elif page == "IT Officer Dashboard":
        if st.session_state.role != "IT Officer":
            st.warning("Access denied — IT Officers only.")
            st.stop()

        st.subheader("🧑‍💻 IT Officer Dashboard")
        df = fetch_tickets()
        if df.empty:
            st.info("No tickets yet.")
        else:
            # selection
            ticket_ids = df["ticket_id"].tolist()
            selected_ticket = st.selectbox("🎟️ Select Ticket", ticket_ids, key="ticket_list")
            ticket = df[df["ticket_id"] == selected_ticket].iloc[0]

            st.markdown(f"### Ticket ID: {ticket['ticket_id']}")
            st.write(f"**Employee:** {ticket['employee_name']}")
            st.write(f"**Department:** {ticket['department']}")
            st.write(f"**Category:** {ticket['category']}")
            st.write(f"**Priority:** {ticket['priority']}")
            st.write(f"**Status:** {ticket['status']}")
            st.info(ticket["description"])

            # attachment
            if ticket.get("attachment"):
                filename = ticket.get("attachment_name") or "attachment"
                try:
                    st.download_button("📎 Download Attachment", data=ticket["attachment"], file_name=filename, key=f"dl_{ticket['ticket_id']}")
                except Exception:
                    st.write(f"Attachment size: {len(ticket['attachment'])} bytes (download not available)")

                if filename.lower().endswith(("png","jpg","jpeg")):
                    try:
                        st.image(Image.open(io.BytesIO(ticket["attachment"])), use_column_width=True)
                    except Exception:
                        st.warning("Unable to preview attachment image.")

            # update
            new_status = st.selectbox("Status", ["Open", "In Progress", "Resolved"], index=["Open","In Progress","Resolved"].index(ticket.get("status","Open")), key="status_sel")
            assigned_to = st.text_input("Assign To", value=ticket.get("assigned_to","") or "", key="assign_to")
            notes = st.text_area("Resolution Notes", value=ticket.get("resolution_notes","") or "", key="res_notes")
            if st.button("💾 Save Update", key="save_update_btn"):
                updates = {"status": new_status, "assigned_to": assigned_to, "resolution_notes": notes}
                if new_status == "Resolved":
                    updates["resolved_at"] = datetime.now().isoformat()
                try:
                    update_ticket(ticket["ticket_id"], updates)
                    st.success(f"✅ Ticket {ticket['ticket_id']} updated successfully!")
                    st.experimental_rerun()
                except Exception:
                    st.error("Update failed:")
                    st.code(traceback.format_exc())

    # Reports & Export
    elif page == "Reports & Export":
        if st.session_state.role != "IT Officer":
            st.warning("Access denied — IT Officers only.")
            st.stop()

        st.subheader("📊 Ticket Reports & Export")
        df = fetch_tickets()
        if df.empty:
            st.info("No tickets yet.")
        else:
            today = datetime.now().date()
            presets = {
                "Today": (today, today),
                "Last 7 Days": (today - timedelta(days=6), today),
                "Last 30 Days": (today - timedelta(days=29), today),
                "Last 6 Months": (today - timedelta(days=182), today),
                "Last 12 Months": (today - timedelta(days=365), today)
            }
            sel = st.selectbox("Range", list(presets.keys()), key="report_range")
            start_d, end_d = presets[sel]
            df["raised_at_dt"] = pd.to_datetime(df["raised_at"])
            mask = (df["raised_at_dt"].dt.date >= start_d) & (df["raised_at_dt"].dt.date <= end_d)
            df_range = df.loc[mask]
            st.metric("Tickets", len(df_range))
            if not df_range.empty:
                df_chart = df_range.copy()
                df_chart["date"] = df_chart["raised_at_dt"].dt.date
                count_df = df_chart.groupby("date").size().reset_index(name="Count")
                st.altair_chart(alt.Chart(count_df).mark_line(point=True).encode(x="date", y="Count"), use_container_width=True)
                st.download_button("⬇️ Download Excel", data=df_to_excel_bytes(df_range), file_name=f"Tickets_{sel}.xlsx", key="export_btn")

    # Future Updates
    elif page == "Future Updates":
        st.subheader("🚀 Upcoming Future Updates")
        st.markdown("""
        <div style='display:flex;flex-direction:column;gap:12px;margin-top:15px;'>
            <div style='background:#fff;border-radius:10px;padding:14px;box-shadow:0 3px 10px rgba(0,0,0,0.08);'>
                <b>📧 Email Notifications</b><p>Automatic alerts when tickets are created, assigned, or resolved.</p>
            </div>
            <div style='background:#fff;border-radius:10px;padding:14px;box-shadow:0 3px 10px rgba(0,0,0,0.08);'>
                <b>📊 Technician Role Access</b><p>Multiple IT roles with restricted access for Technicians and Admins.</p>
            </div>
            <div style='background:#fff;border-radius:10px;padding:14px;box-shadow:0 3px 10px rgba(0,0,0,0.08);'>
                <b>💬 Ticket Chat Thread</b><p>Internal chat-style discussion for each ticket.</p>
            </div>
            <div style='background:#fff;border-radius:10px;padding:14px;box-shadow:0 3px 10px rgba(0,0,0,0.08);'>
                <b>☁️ Cloud Version</b><p>Host securely on company intranet or private cloud.</p>
            </div>
            <div style='background:#fff;border-radius:10px;padding:14px;box-shadow:0 3px 10px rgba(0,0,0,0.08);'>
                <b>🔔 SLA Alerts</b><p>Automatic alerts for delayed or overdue tickets based on SLA rules.</p>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.info("💡 These features are being developed by the Infinium IT Team.")

    # Contact Us
    elif page == "Contact Us":
        st.subheader("📞 Contact IT Helpdesk Team")
        st.markdown("""
        <div class='contact-card' style='text-align:center;'>
            <h3 style='margin-bottom:6px;'>Prince Prajapati</h3>
            <p style='margin-top:0;margin-bottom:4px;'>IT Officer</p>
            <p>📧 <a href='mailto:itofficer@infiniumpharmachem.com' style='color:#2563eb;font-weight:600;'>itofficer@infiniumpharmachem.com</a></p>
            <p>📱 +91 9974896607</p>
            <a href='https://wa.me/919974896607?text=Hello%20Prince%2C%20I%20need%20IT%20Support' target='_blank'>
                <button style='background:#25D366;color:white;border:none;padding:10px 22px;border-radius:8px;font-weight:600;cursor:pointer;box-shadow:0 3px 8px rgba(0,0,0,0.2);transition:all 0.2s ease-in-out;margin-top:10px;'>💬 Chat on WhatsApp</button>
            </a>
        </div>
        """, unsafe_allow_html=True)

    # Footer
    st.markdown("---")
    st.caption("© 2025 Infinium Pharmachem Limited | Developed by Prince Prajapati (IT Officer)")

# Safe run wrapper
def safe_run():
    try:
        main()
    except Exception:
        st.error("⚠️ Application error occurred — see traceback below.")
        st.code(traceback.format_exc())

if __name__ == "__main__":
    safe_run()
