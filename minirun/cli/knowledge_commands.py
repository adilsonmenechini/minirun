"""CLI handlers for /knowledge chat commands.

Extracted from ``cli/main.py`` to keep the main module focused on
the REPL loop and orchestration logic.
"""

from __future__ import annotations

from minirun.memory import KnowledgeStore

KNOWLEDGE_HELP = """
Knowledge Store — Commands:

  /knowledge list                     List all stored facts (up to 50)
  /knowledge search <query>           Search facts by keyword
  /knowledge search <query> --tag t   Filter results by tag
  /knowledge delete <id>              Delete a specific fact by UUID
  /knowledge prune                    Remove all expired facts

Use /help for all chat commands.
"""


def handle_knowledge_list(store: KnowledgeStore) -> None:
    """Handle /knowledge list command."""
    facts = store.list_all(limit=50, offset=0)
    if not facts:
        print("No facts stored.")
        return
    print(f"=== Knowledge Store ({len(facts)} facts) ====")
    print(f"{'ID':36s} | {'Content':50s} | {'Tags':20s} | {'Created'}")
    print("-" * 120)
    for f in facts:
        content_preview = f.content[:50] if len(f.content) > 50 else f.content
        tags_str = ", ".join(f.tags[:3])
        print(
            f"{f.id:36s} | {content_preview:50s} | {tags_str:20s} | {f.created_at[:19]}"
        )


def handle_knowledge_search(store: KnowledgeStore, query: str) -> None:
    """Handle /knowledge search <query> command."""
    if not query:
        print("Usage: /knowledge search <query>")
        return
    facts = store.search(query=query, limit=20)
    if not facts:
        print(f"No facts matching '{query}' found.")
        return
    print(f"=== Search results for '{query}' ({len(facts)} facts) ===")
    for f in facts:
        tags_str = ", ".join(f.tags[:3])
        print(f"  [{f.id[:8]}] {f.content[:80]} (tags: {tags_str})")


def handle_knowledge_delete(store: KnowledgeStore, fact_id: str) -> None:
    """Handle /knowledge delete <id> command."""
    if not fact_id:
        print("Usage: /knowledge delete <id>")
        return
    deleted = store.delete(fact_id)
    if deleted:
        print(f"Deleted fact: {fact_id}")
    else:
        print(f"No fact found with ID: {fact_id}")


def handle_knowledge_prune(store: KnowledgeStore) -> None:
    """Handle /knowledge prune command — remove all expired facts."""
    pruned = store.prune()
    remaining = store.count()
    if pruned:
        print(f"Pruned {pruned} expired fact(s). {remaining} fact(s) remaining.")
    else:
        print("No expired facts to prune.")
        print(f"{remaining} active fact(s) in store.")


def dispatch_knowledge_command(cmd: str, store: KnowledgeStore) -> bool:
    """Dispatch a /knowledge subcommand.

    Returns True if the command was handled, False if it was not recognised.
    """
    if cmd == "/knowledge list":
        handle_knowledge_list(store)
        return True
    if cmd.startswith("/knowledge search "):
        query = cmd[len("/knowledge search ") :].strip()
        handle_knowledge_search(store, query)
        return True
    if cmd.startswith("/knowledge delete "):
        fact_id = cmd[len("/knowledge delete ") :].strip()
        handle_knowledge_delete(store, fact_id)
        return True
    if cmd == "/knowledge prune":
        handle_knowledge_prune(store)
        return True
    if cmd in ("/knowledge", "/knowledge -h", "/knowledge --help"):
        print(KNOWLEDGE_HELP.strip())
        return True
    return False
