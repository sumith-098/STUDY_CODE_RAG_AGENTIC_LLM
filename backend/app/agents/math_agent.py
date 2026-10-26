"""
agents/math_agent.py  --  MathAgent: numeric problems, calculator tool ke saath.

Tools: calculator. Model khud mental math nahi karta -- har arithmetic calculator se karata hai.
Input : prompt (problem).  Output: markdown solution.
"""
from .base import BaseAgent

class MathAgent(BaseAgent):
    name = "math"
    settings_key = "math"
    tool_names = ["calculator"]
    instruction = """
You are StudyPilot's Math Solver.
- Write the formula, substitute values, then solve step by step.
- Use the calculator tool for EVERY arithmetic operation; do not do arithmetic in your head.
- Finish with "Final answer:" on its own line, with units if any.
- Student's language in, same language out.
"""
