# DailyBasket — Product Requirements (Draft v0.2)

**Product:** A Streamlit app for planning grocery purchases, tracking food at home, and reducing avoidable waste.

**Status:** Discussion draft. The decisions at the end are intentionally open for review.

## 1. Problem and goal

People often buy groceries without a clear view of what they already own. Food can then expire or accumulate faster than it is used. DailyBasket should make the current inventory easy to see and call attention to items that need to be used soon.

The initial goal is for each customer to:

1. Make a grocery shopping list.
2. Record what is actually at home, including quantities, nutrition information, and expiry dates.
3. Receive a daily email about expiring items and quantities that may be wasted, with the same summary available in the app.

## 2. Core concepts

| Concept | Meaning |
| --- | --- |
| Shopping list | Items the user intends to buy. These do not count as food at home. |
| Inventory | Items the user has bought and still has. Inventory drives counts and reminders. |
| Product | A recognizable grocery item, such as milk or spinach, with a name, category, and icon or picture. |
| Batch | A quantity of a product acquired on a particular date with its own expiry date. Separate batches allow two purchases of the same product to expire on different days. |

## 3. Intended users and primary workflow

Each customer has one personal account and a private shopping list and inventory. Household sharing is outside the first version. The app should work with quick manual entry; barcode scanning and retailer integrations are outside the first version.

1. Create an account, verify the email address, and set a local time zone and reminder time.
2. Add an item and desired quantity to the shopping list.
3. Check the inventory before shopping to avoid buying something already available.
4. After purchase, move or add the item to inventory, recording quantity and purchase date.
5. Confirm an expiry date, or accept an estimated date for a vegetable.
6. Record nutrition information when useful.
7. Reduce the quantity as food is consumed, or mark a batch as finished or discarded.
8. Read the daily email and decide what to use first.

## 4. Functional requirements

### 4.1 Accounts and data isolation

- Let each customer register, verify an email address, sign in, and sign out.
- Each account owns its own shopping entries, products, images, inventory batches, events, preferences, and reminder history.
- Enforce ownership on every read and write on the server. A customer must never be able to view or change another customer's records, including by changing a URL or record ID.
- Send reminders only to the verified email address associated with the account. Changes to that address require verification before reminders move to it.

### 4.2 Shopping list

- Add, edit, check off, and remove a shopping-list item.
- Store product name, requested quantity, and unit (for example, `2 kg` or `3 pieces`).
- Show whether the product is already in inventory and the total quantity currently on hand.
- Let the user add a purchased shopping-list item to inventory without retyping its name and quantity.
- Show the count of distinct shopping-list items and their requested quantities.

### 4.3 Inventory

- Add, edit, and remove an inventory batch.
- Record product, category, quantity, unit, purchase date, storage method, and expiry date for each batch.
- Show an inventory dashboard with total distinct products, total batches, and quantity per product. Do not combine quantities that use different units.
- Search and filter by product, category, and expiry status.
- Show a small icon or picture for each product. Use a category icon by default; allow an optional custom picture.
- Let the user decrease a batch's remaining quantity after consumption and mark it finished or discarded. Finished and discarded batches should no longer count as stock on hand.
- Keep enough history to distinguish consumed food from discarded food when evaluating waste.

### 4.4 Nutrition

- Let the user enter optional nutrition values for a product: calories, protein, carbohydrates, and fat, with a clear basis such as per 100 g, per 100 ml, or per serving.
- Display the entered values on the product detail view.
- Clearly identify nutrition values as user-entered unless a verified data source is added later. The first version does not calculate daily dietary intake or make health recommendations.

### 4.5 Expiry dates

- Allow the user to enter the package expiry date for any product and edit it later.
- For vegetables without a known date, propose an **estimated freshness date** using the vegetable type, purchase date, and storage method (such as refrigerated or room temperature). Mark the date as an estimate and allow the user to change it.
- Keep estimate rules configurable in the app data so they can be reviewed and updated. A date estimate is a planning aid; the app must not present it as a food-safety guarantee.
- Show `expired`, `expires today`, and `expires soon` states. The initial `soon` window is the next three calendar days, including today; the user should be able to change this preference.

### 4.6 Daily waste-prevention reminder

- Generate a summary each calendar day in the customer's local time zone, recompute it after inventory changes, and make the latest summary visible on the dashboard.
- List batches that are expired or will expire within the configured `soon` window. Show product, quantity remaining, and date.
- Flag a possible surplus when the remaining quantity is greater than the user's expected use before that batch's expiry date. Let the user set an expected use rate per product (for example, `1 kg per week`).
- If expected use is unknown, show `usage rate needed` rather than claiming the quantity will be wasted. The user can still see the expiring quantity.
- Prioritize expired items, then items expiring soon, then possible surplus. Provide actions to mark used, adjust quantity, or dismiss an incorrect alert.
- Email the summary once per customer per local calendar day at the customer's chosen reminder time, including a clear `nothing needs attention today` message when there are no alerts.
- Include the item name, remaining quantity, expiry date, whether that date is estimated, and a link to the customer's dashboard. Avoid claiming that a possible surplus is certain waste.
- Allow the customer to change the reminder time and time zone and pause or resume daily emails without losing inventory data.
- Use a scheduled process independent of the Streamlit page so emails are sent when the customer is offline. Record delivery status, retry temporary failures, and prevent duplicate daily emails.

## 5. Main screens

| Screen | Main content and actions |
| --- | --- |
| Account | Register, verify email, sign in, sign out. |
| Dashboard | Inventory counts, today's reminder, expiring and possible-surplus items, quick add. |
| Shopping list | Items to buy, quantities, on-hand indicator, check off and move to inventory. |
| Inventory | Product cards with icon or picture, quantity, unit, earliest expiry, filters. |
| Product / batch detail | Nutrition, individual batches, expiry source (entered or estimated), edit and consume/discard actions. |
| Settings | Verified email, reminder time and time zone, pause or resume emails, `soon` window, vegetable estimate rules, expected use rates. |

## 6. Minimum data to store

- **Customer account:** ID, verified email, authentication details handled securely, registration state.
- **Product:** ID, owner account ID, name, category, default icon or optional image, optional nutrition values and nutrition basis, optional expected use rate.
- **Shopping-list entry:** ID, owner account ID, product or name, requested quantity, unit, checked state.
- **Inventory batch:** ID, owner account ID, product ID, purchase date, storage method, remaining quantity, unit, expiry date, whether expiry is entered or estimated, status.
- **Inventory event:** ID, owner account ID, batch ID, date, quantity change, reason (`consumed`, `discarded`, or `correction`).
- **Preferences:** owner account ID, local time zone, daily reminder time, email paused state, expiring-soon window.
- **Reminder delivery:** owner account ID, local date, generation and delivery status, send time, retry information.

Persistent storage is required so a Streamlit rerun or server restart does not erase data. A deployed version with separate customer accounts needs a shared database, authenticated server-side access, and an email service. SQLite can support an isolated local prototype, but the customer-facing version should use a database suitable for concurrent accounts.

## 7. MVP acceptance criteria

1. A user can add `spinach, 1 kg` to the shopping list and see it in the list count.
2. After buying it, the user can add it to inventory and see `1 kg` on hand with an icon or picture.
3. If spinach has no package date, the app proposes a clearly labeled estimated freshness date based on its purchase date; the user can override it.
4. The user can add nutrition values with a specified basis and see them again on the product detail view.
5. The dashboard lists a batch expiring within the configured window and shows its remaining quantity.
6. If a use rate is entered and the remaining quantity exceeds expected use before expiry, the daily summary flags a possible surplus and shows the quantities behind that judgment.
7. After the user records consumption, the inventory count and relevant reminder change accordingly.
8. Closing and reopening the app preserves all entered data.
9. Two customers can sign in separately; each sees only their own list, inventory, images, settings, and reminder history.
10. At the configured local time, a verified customer receives one daily email with their current alerts, even when the Streamlit page is closed. If there are no alerts, the email says so.
11. Pausing emails stops delivery without deleting the account or inventory. A failed send is recorded and retried without sending duplicate daily emails.

## 8. Initial boundaries

The first version uses manual entry. Barcode scanning, automatic nutrition lookup, recipe suggestions, store ordering, and dietary advice can be considered after the core inventory and reminder workflow works reliably.

## 9. Decisions to resolve together

1. **Surplus estimate:** Is entering an expected use rate acceptable, or would you prefer a simpler user-set `usual maximum quantity` for each product?
2. **Nutrition entry:** Should nutrition be manual in the first version, or should product lookup be a requirement from day one?
3. **Email content:** Should the app send a short `nothing needs attention today` email on quiet days, or send only when there is something to act on?
