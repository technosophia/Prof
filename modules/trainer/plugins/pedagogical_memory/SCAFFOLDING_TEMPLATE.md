# Pedagogical Memory Scaffolding Template

Use this template in the training program description to help the pedagogical memory plugin generate more accurate facts.

## What the plugin reads from the training program description

The plugin injects the full training program text into the extraction prompt.
The LLM uses this to contextualize observed facts.

Example: if the program says "Week 3 covers recursion", a confusion about recursion can be tagged as a `blocker` rather than a generic `knowledge_state`.

---

## Training Program: [Name]

### Learning objectives
List the specific skills and knowledge the student should acquire, in order.
Be precise: "understand Big-O notation" is better than "learn algorithms".

### Prerequisites
What the student is assumed to know before starting.
The plugin will flag gaps in prerequisites as `blocker` facts.

### Module structure
List modules/weeks/chapters with their topics.
The plugin uses this to contextualise where a student is in the journey.

### Key concepts and common misconceptions
For each major concept, optionally list known misconceptions students often have.
This helps the extraction LLM identify and label `misconception` facts more accurately.

### Assessment signals
How mastery is demonstrated in this program: exercises, explanations, projects.
The plugin uses this to identify `mastered_topic` and `progress_signal` facts.

### Vocabulary
Domain-specific terms used in this training. Helps the LLM parse student
messages correctly without ambiguity.

---

## Tips

- More specific learning objectives → more precise `knowledge_state` facts.
- Named misconceptions → LLM recognises them faster, fewer tokens wasted.
- Without a scaffolding description, the plugin still works but produces generic facts.
