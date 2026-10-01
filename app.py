from datetime import date
import streamlit as st
import dailybasket as db

st.set_page_config(page_title="DailyBasket", page_icon="🧺", layout="wide")
db.initialize()
conn = db.connect()

def user(): return st.session_state.get("user")
def flash(message): st.success(message)

if not user():
    st.title("🧺 DailyBasket")
    login, signup, verify = st.tabs(["Sign in", "Register", "Verify email"])
    with login:
        with st.form("login"):
            email = st.text_input("Email"); password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in"):
                account = db.authenticate(conn, email, password)
                if account: st.session_state.user = dict(account); st.rerun()
                else: st.error("Invalid email or password.")
    with signup:
        with st.form("register"):
            email = st.text_input("Email", key="new_email"); password = st.text_input("Password (8+ characters)", type="password", key="new_password")
            if st.form_submit_button("Create account"):
                try:
                    if len(password) < 8: raise ValueError("Use at least 8 characters.")
                    token = db.register(conn, email, password)
                    if token: st.info(f"Development-only token (no SMTP configured): `{token}`")
                    else: st.success("Verification instructions were sent to your mailbox.")
                except ValueError: st.error("That email is already registered or invalid.")
                except RuntimeError as error: st.error(str(error))
    with verify:
        token = st.text_input("Verification token")
        if st.button("Verify email"):
            st.success("Email verified. You can sign in.") if db.verify_email(conn, token) else st.error("Token not found.")
        with st.form("resend-verification"):
            resend_email = st.text_input("Email for a new verification message")
            if st.form_submit_button("Resend verification"):
                try:
                    resend_token = db.resend_verification(conn, resend_email)
                    if resend_token: st.info(f"Development-only token: `{resend_token}`")
                    else: st.success("If an unverified account is eligible, a new verification message was sent.")
                except RuntimeError as error: st.error(str(error))
    st.stop()

account = user(); owner_id = account['id']; prefs = db.preferences(conn, owner_id)
with st.sidebar:
    st.header("DailyBasket")
    page = st.radio("Navigate", ["Dashboard", "Shopping list", "Inventory", "Settings"])
    if st.button("Sign out"): st.session_state.pop("user"); st.rerun()

if page == "Dashboard":
    st.title("Dashboard")
    batches = db.inventory(conn, owner_id, status="Active")
    products = {row['product_id'] for row in batches}; st.metric("Products on hand", len(products)); st.metric("Active batches", len(batches))
    notices = db.alerts(conn, owner_id)
    st.subheader("Today’s reminder")
    if not notices: st.success("Nothing needs attention today.")
    for item in notices:
        label = item['state'] or "possible surplus"
        st.warning(f"{item['name']}: {item['remaining_quantity']} {item['unit']} — {label}, {item['expiry_date']}" + (" (estimated planning date)" if item['expiry_source']=='estimated' else ""))
        if item['surplus']: st.caption(f"Possible surplus: {item['surplus']['remaining']} {item['unit']} remaining vs {item['surplus']['expected']} expected use before expiry.")
        if item['usage_rate_needed']: st.caption("Usage rate needed to estimate surplus.")
        if st.button(f"Use 1 {item['unit']}", key=f"use{item['id']}"):
            try: db.change_batch(conn, owner_id, item['id'], min(1, item['remaining_quantity']), 'consumed'); st.rerun()
            except ValueError as err: st.error(str(err))

elif page == "Shopping list":
    st.title("Shopping list")
    with st.form("add-shopping", clear_on_submit=True):
        name, quantity, unit = st.columns(3); item_name = name.text_input("Product"); amount = quantity.number_input("Quantity", min_value=0.01, value=1.0); item_unit = unit.text_input("Unit", value="kg")
        if st.form_submit_button("Add item"):
            db.add_shopping(conn, owner_id, item_name, amount, item_unit); st.rerun()
    entries = db.list_shopping(conn, owner_id); st.caption(f"{len(entries)} distinct items")
    for item in entries:
        left, middle, right = st.columns([4,2,2]); left.write(f"{'✓ ' if item['checked'] else ''}**{item['name']}** — {item['quantity']} {item['unit']}"); middle.caption(f"On hand: {item['on_hand']} {item['unit']}")
        if middle.button("Uncheck" if item['checked'] else "Check", key=f"check{item['id']}"):
            db.set_shopping_checked(conn, owner_id, item['id'], not item['checked']); st.rerun()
        if right.button("Buy → inventory", key=f"buy{item['id']}"):
            product_id = db.upsert_product(conn, owner_id, item['name'], "vegetable")
            db.add_batch(conn, owner_id, product_id, item['quantity'], item['unit'], date.today(), "refrigerated")
            conn.execute("UPDATE shopping SET checked=1 WHERE id=? AND owner_id=?", (item['id'],owner_id)); conn.commit(); st.rerun()
        if right.button("Remove", key=f"remove{item['id']}"):
            db.remove_shopping(conn, owner_id, item['id']); st.rerun()
        with st.expander(f"Edit {item['name']}"):
            with st.form(f"edit-shopping{item['id']}"):
                new_name=st.text_input("Product",item['name'],key=f"sn{item['id']}"); new_quantity=st.number_input("Quantity",min_value=0.01,value=float(item['quantity']),key=f"sq{item['id']}"); new_unit=st.text_input("Unit",item['unit'],key=f"su{item['id']}")
                if st.form_submit_button("Save shopping item"):
                    db.edit_shopping(conn,owner_id,item['id'],new_name,new_quantity,new_unit); st.rerun()

elif page == "Inventory":
    st.title("Inventory")
    with st.expander("Add batch", expanded=True):
        with st.form("batch", clear_on_submit=True):
            name, category, qty, unit = st.columns(4); product_name=name.text_input("Product"); product_category=category.selectbox("Category", list(db.CATEGORY_ICONS)); amount=qty.number_input("Quantity", min_value=0.01, value=1.0); batch_unit=unit.text_input("Unit", value="kg")
            bought, storage, expiry = st.columns(3); purchased=bought.date_input("Purchase date", date.today()); storage_method=storage.selectbox("Storage", ["refrigerated","room"]); expiry_date=expiry.date_input("Package expiry (optional)", value=None)
            basis, calories, use_rate = st.columns(3); nutrition_basis=basis.selectbox("Nutrition basis", ["Not entered", "per 100 g", "per 100 ml", "per serving"]); nutrition_calories=calories.number_input("Calories (optional)", min_value=0.0); expected_rate=use_rate.number_input("Expected use / week (0 = unknown)", min_value=0.0)
            if st.form_submit_button("Add inventory"):
                nutrition = {"calories": nutrition_calories} if nutrition_basis != "Not entered" else None
                product_id=db.upsert_product(conn, owner_id, product_name, product_category, nutrition, None if nutrition_basis == "Not entered" else nutrition_basis, expected_rate or None, batch_unit if expected_rate else None); db.add_batch(conn, owner_id, product_id, amount, batch_unit, purchased, storage_method, expiry_date); st.rerun()
    query, filter_category, filter_status = st.columns(3); search=query.text_input("Search"); category_filter=filter_category.selectbox("Category",["All",*db.CATEGORY_ICONS]); status_filter=filter_status.selectbox("Expiry / status",["Active","Expired","Soon","All"]); rows = db.inventory(conn, owner_id, search, category_filter, status_filter)
    for batch in rows:
        product=db.product_detail(conn,owner_id,batch['product_id']); icon=db.CATEGORY_ICONS.get(batch['category'],'🛒')
        if product['image_data']: st.image(product['image_data'],width=48)
        st.write(f"{icon} **{batch['name']}** — {batch['remaining_quantity']} {batch['unit']}, expires {batch['expiry_date']} ({batch['expiry_source']})")
        if batch['nutrition_basis']: st.caption(f"User-entered nutrition ({batch['nutrition_basis']}): {batch['nutrition_json']}")
        col1,col2=st.columns(2)
        if col1.button("Consume 1", key=f"consume{batch['id']}"):
            try: db.change_batch(conn, owner_id,batch['id'],min(1,batch['remaining_quantity']),'consumed'); st.rerun()
            except (ValueError, RuntimeError) as error: st.error(str(error))
        if col2.button("Discard all", key=f"discard{batch['id']}"): db.change_batch(conn, owner_id,batch['id'],batch['remaining_quantity'],'discarded'); st.rerun()
        with st.expander(f"Details and edit: {batch['name']} ({batch['id']})"):
            st.caption(f"Purchase: {batch['purchase_date']} · Storage: {batch['storage']} · Status: {batch['status']}")
            st.write(f"Nutrition (user-entered): {product['nutrition_json']} — {product['nutrition_basis'] or 'not entered'}")
            with st.form(f"batch-edit{batch['id']}"):
                e_quantity=st.number_input("Original quantity",min_value=0.01,value=float(batch['quantity']),key=f"bq{batch['id']}"); e_unit=st.text_input("Unit",batch['unit'],key=f"bu{batch['id']}"); e_purchase=st.date_input("Purchase date",date.fromisoformat(batch['purchase_date']),key=f"bp{batch['id']}"); e_storage=st.selectbox("Storage",["refrigerated","room"],index=["refrigerated","room"].index(batch['storage']),key=f"bs{batch['id']}"); override=st.date_input("Override expiry (leave blank to estimate)",date.fromisoformat(batch['expiry_date']) if batch['expiry_source']=='entered' else None,key=f"be{batch['id']}")
                if st.form_submit_button("Save batch"):
                    db.edit_batch(conn,owner_id,batch['id'],e_quantity,e_unit,e_purchase,e_storage,override); st.rerun()
            with st.form(f"correct{batch['id']}"):
                corrected=st.number_input("Correct remaining quantity",min_value=0.0,value=float(batch['remaining_quantity']),key=f"cr{batch['id']}")
                if st.form_submit_button("Record correction"): db.correct_batch(conn,owner_id,batch['id'],corrected); st.rerun()
            action_one,action_two=st.columns(2)
            if action_one.button("Mark finished",key=f"finish{batch['id']}"): db.finish_batch(conn,owner_id,batch['id']); st.rerun()
            if action_two.button("Remove (keeps event history)",key=f"delete{batch['id']}"): db.remove_batch(conn,owner_id,batch['id']); st.rerun()
            with st.form(f"product{batch['product_id']}"):
                rate=st.number_input("Expected use per week (0 unknown)",min_value=0.0,value=float(product['use_rate'] or 0),key=f"rate{batch['product_id']}"); rate_unit=st.text_input("Use-rate unit",product['use_unit'] or batch['unit'],key=f"rateu{batch['product_id']}"); upload=st.file_uploader("Optional product image",type=["png","jpg","jpeg","webp"],key=f"image{batch['product_id']}")
                if st.form_submit_button("Save product details"):
                    image=upload.getvalue() if upload else None; db.update_product(conn,owner_id,batch['product_id'],product['category'],db.json_load(product['nutrition_json']),product['nutrition_basis'],rate,rate_unit,image,upload.type if upload else None); st.rerun()

else:
    st.title("Settings")
    import json
    with st.form("settings"):
        timezone=st.text_input("Time zone (IANA)", prefs['timezone']); reminder=st.time_input("Reminder time"); paused=st.checkbox("Pause emails", bool(prefs['paused'])); soon=st.number_input("Soon window (calendar days including today)",min_value=1,max_value=30,value=prefs['soon_days'])
        rules=st.text_area("Freshness estimate rules (JSON days by type/storage)", prefs['estimate_rules'])
        if st.form_submit_button("Save settings"):
            try: __import__('zoneinfo').ZoneInfo(timezone); json.loads(rules); db.update_preferences(conn,owner_id,timezone=timezone,reminder_time=str(reminder)[:5],paused=int(paused),soon_days=soon,estimate_rules=rules); st.success("Saved.")
            except Exception: st.error("Use an IANA zone, e.g. Asia/Kolkata.")
    st.caption("Vegetable freshness estimates are configurable planning aids, not food-safety guarantees. Nutrition is manual and user-entered.")
    st.subheader("Change reminder email")
    pending=conn.execute("SELECT pending_email FROM users WHERE id=?",(owner_id,)).fetchone()['pending_email']
    st.caption(f"Current verified destination: {account['email']}. " + (f"Awaiting verification for {pending}." if pending else ""))
    with st.form("email-change"):
        new_email=st.text_input("New email")
        if st.form_submit_button("Send verification"):
            try:
                token=db.request_email_change(conn,owner_id,new_email)
                if token: st.info(f"Development-only token (no SMTP configured): `{token}`")
                else: st.success("Verification instructions were sent to the new address. Existing reminder destination is unchanged until verified.")
            except ValueError as error: st.error(str(error))
