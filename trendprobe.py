"""Serienfreie Suche für deutsche Spiele heute (1./2./3. Liga)."""
import sys
sys.argv = ["ohneserie.py", r"^Germany\. (Bundesliga|2\. Bundesliga|3\. Liga)$", "14"]
import ohneserie
ohneserie.main()
