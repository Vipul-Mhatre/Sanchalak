"""
Ingestion pipeline for customer data corpus.
Parses markdown files into typed records, chunks/embeds them, 
and stores in ChromaDB with metadata tagging.
"""

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DATASET_DIR = Path(__file__).resolve().parent.parent / "dataset"
CHROMA_DIR = Path(__file__).resolve().parent / "chroma_db"
HASH_FILE = Path(__file__).resolve().parent / "file_hashes.json"
COLLECTION_NAME = "customer_data"


def _get_embedding_fn():
    """Sentence-transformer embedding function for ChromaDB."""
    return embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )


def _get_collection(client: chromadb.ClientAPI):
    """Get or create the customer_data collection."""
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=_get_embedding_fn(),
        metadata={"hnsw:space": "cosine"},
    )


# ---------------------------------------------------------------------------
# Parsers — one per record type
# ---------------------------------------------------------------------------

def _parse_md_table(text: str, skip_header_lines: int = 0) -> list[dict]:
    """
    Generic markdown pipe-table parser.
    Returns list of dicts keyed by header column names.
    """
    lines = text.strip().splitlines()
    # Skip any non-table leading lines (title, description, blank)
    table_lines = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and "|" in stripped[1:]:
            in_table = True
            table_lines.append(stripped)
        elif in_table:
            break  # end of table block

    if len(table_lines) < 3:
        return []

    # First line = headers, second = separator, rest = data
    headers = [h.strip() for h in table_lines[0].split("|") if h.strip()]
    data_rows = table_lines[2:]  # skip header + separator

    records = []
    for row in data_rows:
        cells = [c.strip() for c in row.split("|") if c.strip() != ""]
        if len(cells) < len(headers):
            cells += [""] * (len(headers) - len(cells))
        record = {}
        for i, header in enumerate(headers):
            record[header] = cells[i] if i < len(cells) else ""
        records.append(record)
    return records


def parse_accounts() -> list[dict]:
    """Parse accounts.md → list of account records."""
    text = (DATASET_DIR / "accounts.md").read_text(encoding="utf-8")
    rows = _parse_md_table(text)
    records = []
    for row in rows:
        acct_id = row.get("ID", "").strip()
        if not acct_id:
            continue
        name = row.get("Name", "")
        industry = row.get("Industry", "")
        region = row.get("Region", "")
        tier = row.get("Tier", "")
        health = row.get("Health", "")
        arr = row.get("ARR", "")
        owner = row.get("Owner", "")
        devices = row.get("Devices", "")

        content = (
            f"Account: {name} (ID: {acct_id})\n"
            f"Industry: {industry} | Region: {region} | Tier: {tier}\n"
            f"Health: {health} | ARR: {arr}\n"
            f"Owner: {owner}\n"
            f"Devices: {devices}"
        )
        records.append({
            "id": acct_id,
            "type": "account",
            "content": content,
            "metadata": {
                "record_type": "account",
                "account_name": name,
                "account_id": acct_id,
                "industry": industry,
                "region": region,
                "tier": tier,
                "health": health,
                "arr": arr,
                "owner": owner,
            },
        })
    return records


def parse_feature_requests() -> list[dict]:
    """Parse feature_requests.md → list of FR records with synthetic IDs."""
    text = (DATASET_DIR / "feature_requests.md").read_text(encoding="utf-8")
    rows = _parse_md_table(text)
    records = []
    for i, row in enumerate(rows, start=1):
        fr_id = f"FR-{i:04d}"
        title = row.get("Title", "")
        product_area = row.get("Product Area", "")
        status = row.get("Status", "")
        accounts = row.get("Accounts Requesting", "")
        mentions = row.get("Mentions", "")
        revenue = row.get("Est. Revenue Impact", "")

        content = (
            f"Feature Request: {title} (ID: {fr_id})\n"
            f"Product Area: {product_area} | Status: {status}\n"
            f"Accounts Requesting: {accounts}\n"
            f"Mentions: {mentions} | Est. Revenue Impact: {revenue}"
        )
        records.append({
            "id": fr_id,
            "type": "feature_request",
            "content": content,
            "metadata": {
                "record_type": "feature_request",
                "feature_request_id": fr_id,
                "title": title,
                "product_area": product_area,
                "status": status,
                "accounts_requesting": accounts,
                "mentions": mentions,
                "revenue_impact": revenue,
            },
        })
    return records


def parse_issues() -> list[dict]:
    """Parse issues.md → list of issue records."""
    text = (DATASET_DIR / "issues.md").read_text(encoding="utf-8")
    rows = _parse_md_table(text)
    records = []
    for row in rows:
        issue_id = row.get("ID", "").strip()
        if not issue_id:
            continue
        account = row.get("Account", "")
        category = row.get("Category", "")
        status = row.get("Status", "")
        title = row.get("Title", "")

        content = (
            f"Issue: {title} (ID: {issue_id})\n"
            f"Account: {account} | Category: {category} | Status: {status}"
        )
        records.append({
            "id": issue_id,
            "type": "issue",
            "content": content,
            "metadata": {
                "record_type": "issue",
                "issue_id": issue_id,
                "account_name": account,
                "category": category,
                "status": status,
                "title": title,
            },
        })
    return records


def parse_tasks() -> list[dict]:
    """Parse tasks.md → list of task records."""
    text = (DATASET_DIR / "tasks.md").read_text(encoding="utf-8")
    rows = _parse_md_table(text)
    records = []
    for row in rows:
        task_id = row.get("ID", "").strip()
        if not task_id:
            continue
        account = row.get("Account", "")
        title = row.get("Title", "")
        assignee = row.get("Assignee", "")
        priority = row.get("Priority", "")
        status = row.get("Status", "")
        due = row.get("Due", "")

        content = (
            f"Task: {title} (ID: {task_id})\n"
            f"Account: {account} | Assignee: {assignee}\n"
            f"Priority: {priority} | Status: {status} | Due: {due}"
        )
        records.append({
            "id": task_id,
            "type": "task",
            "content": content,
            "metadata": {
                "record_type": "task",
                "task_id": task_id,
                "account_name": account,
                "title": title,
                "assignee": assignee,
                "priority": priority,
                "status": status,
                "due_date": due,
            },
        })
    return records


def parse_meeting_notes() -> list[dict]:
    """Parse meeting_notes.md → list of meeting note records (heading-based sections)."""
    text = (DATASET_DIR / "meeting_notes.md").read_text(encoding="utf-8")
    # Split on ## MTG-NNNN headings
    sections = re.split(r"(?=^## MTG-\d+)", text, flags=re.MULTILINE)
    records = []
    for section in sections:
        section = section.strip()
        if not section.startswith("## MTG-"):
            continue

        # Extract meeting ID and account from header
        header_match = re.match(r"## (MTG-\d+):\s*(.+)", section)
        if not header_match:
            continue
        mtg_id = header_match.group(1)
        account = header_match.group(2).strip()

        # Extract fields
        topic_match = re.search(r"\*\*Topic:\*\*\s*(.+)", section)
        attendees_match = re.search(r"\*\*Attendees:\*\*\s*(.+)", section)
        date_match = re.search(r"\*\*Date:\*\*\s*(.+)", section)

        topic = topic_match.group(1).strip() if topic_match else ""
        attendees = attendees_match.group(1).strip() if attendees_match else ""
        date = date_match.group(1).strip() if date_match else ""

        # Extract action items
        action_items = []
        in_actions = False
        for line in section.splitlines():
            if "**Action Items:**" in line:
                in_actions = True
                continue
            if in_actions and line.strip().startswith("- "):
                action_items.append(line.strip()[2:])
            elif in_actions and line.strip() == "":
                break

        actions_text = "; ".join(action_items) if action_items else "None listed"

        content = (
            f"Meeting Note: {topic} (ID: {mtg_id})\n"
            f"Account: {account} | Date: {date}\n"
            f"Attendees: {attendees}\n"
            f"Action Items: {actions_text}"
        )
        records.append({
            "id": mtg_id,
            "type": "meeting_note",
            "content": content,
            "metadata": {
                "record_type": "meeting_note",
                "meeting_id": mtg_id,
                "account_name": account,
                "topic": topic,
                "date": date,
                "attendees": attendees,
            },
        })
    return records


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def get_all_records() -> list[dict]:
    """Parse all dataset files and return combined record list."""
    all_records = []
    all_records.extend(parse_accounts())
    all_records.extend(parse_feature_requests())
    all_records.extend(parse_issues())
    all_records.extend(parse_tasks())
    all_records.extend(parse_meeting_notes())
    return all_records


def _compute_file_hashes() -> dict[str, str]:
    """Compute MD5 hashes for all dataset files."""
    hashes = {}
    for f in DATASET_DIR.glob("*.md"):
        content = f.read_bytes()
        hashes[f.name] = hashlib.md5(content).hexdigest()
    return hashes


def _load_saved_hashes() -> dict[str, str]:
    """Load previously saved file hashes."""
    if HASH_FILE.exists():
        return json.loads(HASH_FILE.read_text())
    return {}


def _save_hashes(hashes: dict[str, str]):
    """Save current file hashes."""
    HASH_FILE.write_text(json.dumps(hashes, indent=2))


def _file_to_record_type(filename: str) -> str:
    """Map filename to record type."""
    mapping = {
        "accounts.md": "account",
        "feature_requests.md": "feature_request",
        "issues.md": "issue",
        "tasks.md": "task",
        "meeting_notes.md": "meeting_note",
    }
    return mapping.get(filename, "unknown")


def _parser_for_file(filename: str):
    """Get the parser function for a given file."""
    mapping = {
        "accounts.md": parse_accounts,
        "feature_requests.md": parse_feature_requests,
        "issues.md": parse_issues,
        "tasks.md": parse_tasks,
        "meeting_notes.md": parse_meeting_notes,
    }
    return mapping.get(filename)


def build_index() -> dict:
    """
    Full index build: parse all files, embed, store in ChromaDB.
    Returns summary stats.
    """
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # Delete and recreate to ensure clean state
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = _get_collection(client)

    all_records = get_all_records()

    # Batch upsert (ChromaDB limit is 5461 per batch)
    batch_size = 500
    for i in range(0, len(all_records), batch_size):
        batch = all_records[i : i + batch_size]
        ids = [r["id"] for r in batch]
        documents = [r["content"] for r in batch]
        metadatas = [r["metadata"] for r in batch]
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

    # Save file hashes
    _save_hashes(_compute_file_hashes())

    stats = {}
    for r in all_records:
        rtype = r["type"]
        stats[rtype] = stats.get(rtype, 0) + 1
    stats["total"] = len(all_records)
    return stats


def reindex_delta() -> dict:
    """
    Incremental reindex: only re-embed files that changed since last index.
    Returns summary of what changed.
    """
    current_hashes = _compute_file_hashes()
    saved_hashes = _load_saved_hashes()

    changed_files = []
    for filename, hash_val in current_hashes.items():
        if saved_hashes.get(filename) != hash_val:
            changed_files.append(filename)

    # Check for deleted files
    deleted_files = [f for f in saved_hashes if f not in current_hashes]

    if not changed_files and not deleted_files:
        return {"status": "no_changes", "changed_files": [], "deleted_files": []}

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = _get_collection(client)

    result = {
        "status": "updated",
        "changed_files": changed_files,
        "deleted_files": deleted_files,
        "records_updated": 0,
        "records_deleted": 0,
    }

    # Handle changed files
    for filename in changed_files:
        record_type = _file_to_record_type(filename)
        parser = _parser_for_file(filename)
        if not parser:
            continue

        # Delete old records of this type
        try:
            existing = collection.get(where={"record_type": record_type})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
                result["records_deleted"] += len(existing["ids"])
        except Exception:
            pass

        # Parse and insert new records
        new_records = parser()
        if new_records:
            batch_size = 500
            for i in range(0, len(new_records), batch_size):
                batch = new_records[i : i + batch_size]
                ids = [r["id"] for r in batch]
                documents = [r["content"] for r in batch]
                metadatas = [r["metadata"] for r in batch]
                collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            result["records_updated"] += len(new_records)

    # Handle deleted files
    for filename in deleted_files:
        record_type = _file_to_record_type(filename)
        try:
            existing = collection.get(where={"record_type": record_type})
            if existing["ids"]:
                collection.delete(ids=existing["ids"])
                result["records_deleted"] += len(existing["ids"])
        except Exception:
            pass

    # Save updated hashes
    _save_hashes(current_hashes)
    return result


def search_customer_data(
    query: str,
    n_results: int = 10,
    record_type: Optional[str] = None,
    account_name: Optional[str] = None,
    industry: Optional[str] = None,
) -> list[dict]:
    """
    Search customer data in ChromaDB.
    Returns list of matching records with scores.
    """
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = _get_collection(client)

    # Build where filter
    where_filter = None
    conditions = []
    if record_type:
        conditions.append({"record_type": record_type})
    if account_name:
        conditions.append({"account_name": {"$eq": account_name}})
    if industry:
        conditions.append({"industry": {"$eq": industry}})

    if len(conditions) == 1:
        where_filter = conditions[0]
    elif len(conditions) > 1:
        where_filter = {"$and": conditions}

    try:
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter,
        )
    except Exception:
        # Fallback without filter if filter causes issues
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
        )

    records = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            record = {
                "id": doc_id,
                "content": results["documents"][0][i] if results["documents"] else "",
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 1.0,
            }
            records.append(record)
    return records


# ---------------------------------------------------------------------------
# CLI entry point for testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Parsing dataset files ===")
    accounts = parse_accounts()
    print(f"  Accounts: {len(accounts)}")

    frs = parse_feature_requests()
    print(f"  Feature Requests: {len(frs)}")

    issues = parse_issues()
    print(f"  Issues: {len(issues)}")

    tasks = parse_tasks()
    print(f"  Tasks: {len(tasks)}")

    meetings = parse_meeting_notes()
    print(f"  Meeting Notes: {len(meetings)}")

    total = len(accounts) + len(frs) + len(issues) + len(tasks) + len(meetings)
    print(f"\n  TOTAL: {total} records")

    print("\n=== Building ChromaDB index ===")
    stats = build_index()
    print(f"  Index stats: {stats}")

    print("\n=== Testing search ===")
    results = search_customer_data("firmware update issues")
    print(f"  Search 'firmware update issues' → {len(results)} results")
    for r in results[:3]:
        print(f"    [{r['id']}] (dist={r['distance']:.3f}) {r['content'][:80]}...")
