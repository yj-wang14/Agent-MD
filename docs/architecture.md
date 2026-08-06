# Architecture

Agent-MD combines a reasoning agent, a rule-based campaign agent, scientific tools, persistent campaign state and provenance, validation, and conditional human review. The reasoning agent supports campaign planning and unresolved review events. The rule-based campaign agent reads the approved specification and state, selects permitted actions, invokes tools, archives accepted states, and initializes successors through accepted-state inheritance.
