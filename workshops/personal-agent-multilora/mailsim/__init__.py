"""Local mail simulator for PersonaDesk labs.

A tiny SMTP + IMAP server (standard library only) where a fixed set of local addresses can
email each other. Nothing is relayed: recipients outside ``config/mailboxes.json`` are refused.
"""
