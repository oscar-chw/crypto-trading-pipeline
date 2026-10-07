"""Thin adapters from the bot's own code to the crypto-desk-blueprint stage Protocols (pipeline.protocols).

Each adapter calls the bot's code and only translates types; none of them is on the live trading path.
impl.py exposes the factories the blueprint's conformance suites call (scripts/conformance.sh).
"""
