<!-- 
RULES: 
1. DO NOT DELETE OLD ENTRIES.
2. ALWAYS APPEND NEW ENTRIES AT THE TOP (after this header) OR BOTTOM (chronological).
3. PRESERVE HISTORY.
-->

## [2026-01-04] App Icon Modernization

### Summary
Updated the application icon to a modern, user-provided design. The new icon better aligns with macOS aesthetics and correctly supports high-resolution displays (Retina).

### Key Actions
1.  **Icon Replacement:**
    *   Replaced the legacy icon (flat, sharp edges) with a new user-supplied design (`tgflow_no_white_bg...`).
    *   Generated a complete macOS iconset including all standard sizes: 16x16, 32x32, 128x128, 256x256, 512x512 (plus @2x variants).
    *   Converted the iconset to the standard Apple ICNS format (`icon.icns`).
2.  **Cleanup:**
    *   Removed obsolete icon files (`icon.png`, `.ico`).
    *   Ensured the new `icon.icns` is correctly placed in both the project root and `resources/` directory.
3.  **Verification:**
    *   Verified correct rendering in the Dock and application window header using `main.py`.

---

## [2026-01-04] Media Broadcasting Improvements - Captions

### Summary
Addressed user request to send media with captions instead of separate messages in broadcasts. Implemented logic in `mini_broadcast.py` to support captions for photos, videos, and documents, significantly modifying the default behavior to prefer "single message" delivery.

### Key Changes

1.  **Refactored `mini_broadcast.py` (`_send_single`):**
    *   **Previous Behavior:** Media files were sent first, followed by a separate text message `send_message`. This caused rate limit issues and dual notifications.
    *   **New Logic:**
        *   Checks if text length <= 1024 characters (Telegram caption limit).
        *   If valid, attaches text as `caption` to the first media file.
        *   If text is too long or no media exists, falls back to separate `send_message` or text-only message.
        *   Explicitly handles different media types (Photo, Video, Document) with caption support.

2.  **Verified `main.py`:**
    *   Confirmed that `OptimizedBroadcastWorker` already contained similar robust logic, so no changes were needed there.

### System State
*   **Mini Broadcast:** Now sends cleaner single messages for media+text broadcasts.
*   **Classic Broadcast:** Unchanged (behavior matches new Mini Broadcast logic).

---

## [2026-01-03] Final Fix: Preserve Markdown Links in HTML Text

### Summary
**Root Cause Identified:** The issue was that QTextEdit saves links as Markdown text (`[text](url)`) inside HTML, not as `<a>` tags. When `_escape_md()` processed this text, it escaped the `[` and `]` characters, turning `[INWAYUP | БИЗНЕС](url)` into `\[INWAYUP | БИЗНЕС\](url)`, which Telegram rendered as literal backslashes.

### Solution
Modified `_escape_md()` in both `main.py` and `mini_broadcast.py` to:
1. **Detect ready-made Markdown links** using regex pattern `\[[^\]]+\]\([^\)]+\)`
2. **Temporarily replace them with placeholders** before escaping special characters
3. **Restore the links unchanged** after escaping, preserving their Markdown syntax

This ensures that Markdown links embedded in HTML text (as saved by QTextEdit) are not broken by escaping, while still properly escaping special characters in regular text.

### Testing
Verified with actual `BusinessOffer.txt` content - links now convert correctly without backslashes:
- Input: `— [INWAYUP | БИЗНЕС](https://t.me/+sA7TFWJHbBU2ZTk6)`
- Output: `— [INWAYUP | БИЗНЕС](https://t.me/+sA7TFWJHbBU2ZTk6)` ✅

---

## [2026-01-03] Markdown Parsing Fix - Alignment with Working Scripts

### Summary
Fixed persistent issue where broadcast messages contained visible backslashes (e.g., `\INWAYUP` instead of `INWAYUP`). After analyzing working implementations in `run_group_broadcast.py` and `antispam_broadcast.py`, identified that the problem was in `_escape_md()` function which was removing ALL backslashes, breaking proper Markdown escaping.

### Key Changes

1.  **Fixed `_escape_md()` Function (`main.py`):**
    *   **Previous Issue:** Function was removing all backslashes with `text.replace('\\', '')` before escaping special characters, which broke legitimate Markdown escaping.
    *   **Fix:** Removed aggressive backslash stripping. Now function only escapes Markdown special characters (`*`, `` ` ``, `[`, `]`) that are NOT already escaped (using negative lookbehind `(?<!\\)`).
    *   **Result:** Text processing now matches the approach in `run_group_broadcast.py` and `antispam_broadcast.py`, which use clean Markdown text with `parse_mode=enums.ParseMode.MARKDOWN`.

2.  **Unified ParseMode:**
    *   Changed `ParseMode.DEFAULT` to `ParseMode.MARKDOWN` in media fallback path (line 1475) to ensure consistent Markdown parsing throughout all send paths.

3.  **Alignment with Working Scripts:**
    *   Verified that all `send_message` calls use `parse_mode=ParseMode.MARKDOWN` and `disable_web_page_preview` parameters, matching the successful implementation in `run_group_broadcast.py` and `antispam_broadcast.py`.

### System State
*   **Text Processing:** Markdown escaping now works correctly without removing legitimate backslashes.
*   **Parse Mode:** Consistent `MARKDOWN` mode used throughout, matching working broadcast scripts.

---

## [2026-01-03] Aggressive Backslash Cleanup

### Summary
Addressed a persistent issue where broadcast messages contained "extra" backslashes (e.g. `\INWAYUP` instead of `INWAYUP`). Investigation suggested that the input text itself contained backslashes (possibly artifacts from copy-paste or other tools). To solve this definitively, `_escape_md` now aggressively strips ALL backslashes from the input text before processing Markdown escapes.

### Key Changes

1.  **Backslash Stripping (`main.py`, `mini_broadcast.py`):**
    *   **Action:** Modified `_escape_md` to execute `text = text.replace('\\', '')` at the very beginning.
    *   **Reasoning:** The user consistently reported "extra" backslashes appearing in the output (e.g., surrounding names). Since `html_to_md` does not generate them, and `MD_SPECIALS` no longer includes `\`, the backslashes must be present in the source text. Stripping them ensures a clean visual output for the end-user (Telegram reader), aligning with how other tools in the project (like `run_group_broadcast.py`) handle text normalization.
    *   **Implication:** Literal backslashes cannot be sent in messages anymore. This is considered an acceptable trade-off for a marketing broadcast tool where backslashes are typically unwanted artifacts.

2.  **Previous Attempt (Reverted/Augmented):**
    *   The previous fix (removing `\` from `MD_SPECIALS`) was insufficient because it only prevented *doubling* of backslashes, but did not remove *existing* single backslashes which Telegram Legacy Markdown renders visibly if they don't escape a special character.

---

## [2026-01-03] Markdown Formatting & Error Handling Improvements

### Summary
Addressed a formatting regression in broadcast messages where backslashes were being double-escaped (e.g., `\INWAYUP` instead of `INWAYUP`). Implemented a fix in the Markdown converter to stop auto-escaping backslashes, allowing manual escaping if needed but preventing visual artifacts in standard text. Also improved error reporting in the UI.

### Key Changes

1.  **Markdown Converter Fix (`main.py`, `mini_broadcast.py`):**
    *   **Issue:** The `html_to_md` converter included `\` in the list of special characters (`MD_SPECIALS`) to be automatically escaped. This caused single backslashes in user content (or generated by other tools) to become double backslashes (`\\`) in the final output, which Telegram renders visibly.
    *   **Fix:** Removed `\` from `MD_SPECIALS`.
    *   **Result:** Backslashes are now passed through as-is. This means a user-typed `\` will act as an escape character for Telegram (e.g., `\*` -> `*`), and won't appear as a literal character unless double-escaped by the user (`\\`). This cleans up the output for texts like `— \INWAYUP`.

2.  **Documentation:**
    *   Updated `FORMAT_GUIDE.md` to reflect the new escaping strategy.
    *   Updated `CHANGELOG.md` with version v1.2 details.

3.  **Error Handling (from previous session v1.1):**
    *   Implemented "human-readable" error messages for common Telegram errors (`ALLOW_PAYMENT_REQUIRED`, `CHAT_WRITE_FORBIDDEN`, etc.) in `mini_broadcast.py` and `main.py`.

---

## [2026-01-02] Folder Distribution & Network Setup (Complete)

### Summary
Successfully configured 5 new accounts (`Account 1` - `Account 5`) with the required folder structure (`папка1`, `папка2`, `папка3`) mirrored from the Admin account. All accounts have joined the underlying private chats and can broadcast messages.

### Key Events & Actions

1.  **Authorization (Previously):**
    *   All accounts authorized via QR Code method.

2.  **Folder Distribution Attempt 1 (Clone Script):**
    *   Tried cloning folders programmatically (`tools/clone_folders.py`).
    *   **Issue:** Failed for private chats (Groups 1-6) because new accounts didn't have access/invites to them.
    *   **Result:** Only public channels were cloned.

3.  **Incident: Accidental Cleanup:**
    *   **What happened:** Executed `tools/cleanup_folders.py` on `Account 1` to remove "failed" clones, but inadvertently removed **all** folders, including original ones present on the account from before (e.g., `AiGen`, `Биржи`, `Удаленка`).
    *   **Resolution:**
        *   Parsed logs from a previous inspection step to identify deleted folders.
        *   Created `tools/restore_original_folders.py` to restore them.
        *   **Outcome:** Restored folder structure for `AiGen`, `Биржи`, `Рабочие чаты`, etc. (Content partially restored where usernames were public).

4.  **Folder Distribution Attempt 2 (Chat Folder Links):**
    *   Extracted `t.me/addlist/...` links from Admin's Saved Messages.
    *   Tried `tools/join_folder_links.py`.
    *   **Issue:** Links worked for Account 2 (already joined), but failed for others with `FILTER_INCLUDE_EMPTY`.
    *   **Root Cause:** The `addlist` links did not grant automatic join rights to the specific private chats involved, or accounts were not yet members.

5.  **Folder Distribution Attempt 3 (Direct Invites - Success):**
    *   (Restored content partial) Used direct invite links/adding members to ensure all accounts have access to the private groups.
    *   Successfully replicated folder structure.

---

## 2025-12-28 (Update)
- **Action:** Removed Licensing and Profile logic.
  - Removed `Profile` tab from UI.
  - Removed `LicenseClient`, `LicenseStorage` usage.
  - Removed `check_license`, `reserve_usage`, `commit_usage` logic.
  - Application now runs without authorization requirements.
  - Cleaned up imports and methods in `main.py`.
- **Status:** App launches successfully, Profile tab is gone.
