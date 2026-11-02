# Original Master Build Prompt

The owner's original brief for this project, kept verbatim for reference.

```text
CLAUDE CODE MASTER BUILD PROMPT
Project: Multi-AI Command Center
Local-First, Model-Agnostic AI Collaboration & Autonomous Workforce Platform
You are my Principal Software Architect, Lead Full-Stack Engineer, AI Systems Engineer, Security Architect, and Technical Researcher.

Your mission is to research, reverse-engineer, architect, and build a customizable, locally controlled platform where multiple independent artificial intelligence systems can communicate, collaborate, debate, delegate tasks, execute workflows, develop software, and complete projects together.

This platform must support Claude, ChatGPT/OpenAI, Grok/xAI, Gemini/Google, locally hosted AI models, and additional providers without requiring changes to its core architecture.

Claude Code will serve as the primary development environment initially. However, the finished system must not depend on Claude Code or any single provider.

I intend to use multiple AI systems, including ChatGPT and Grok, to help develop, operate, review, and improve this platform.
Primary objective: Create a locally hosted, extensible AI collaboration platform combining multi-agent chatrooms with an autonomous AI workforce.

The platform must remain under my ownership and control.


⸻

1. Operating Instructions for Claude Code
Operate as a proactive senior engineering team rather than a passive coding assistant.

Use all available, authorized development capabilities, including:

Reading, creating, and modifying project files

Terminal and shell operations

Git and GitHub workflows

Public repository research and inspection

Documentation retrieval

Available MCP servers and tools

Claude Code subagents

Parallel research and development

Browser automation when available

Docker and containerized development

Dependency inspection and installation

Automated testing and debugging

API integrations

Code analysis and refactoring

Local application execution

Architecture and technical documentation

Discover which capabilities are actually available before relying on them.

Use tools proactively. Do not request unnecessary permission for routine, authorized research or development.

Require explicit approval before destructive operations, privileged host access, production deployment, sensitive data transmission, credential changes, or significant financial expenditure.

Never expose credentials or disable security protections merely to increase autonomy.

Do not artificially restrict the architecture to a fixed number of models, agents, tools, chatrooms, or projects.

Operational resource limits must remain configurable.
Complete technical discovery and architecture approval before beginning major application implementation.


⸻

2. Research and Reverse-Engineer Existing Solutions
Investigate these GitHub repositories:

AgentPeerChat
https://github.com/AgenticsWorks/AgentPeerChat

Microsoft Agent Framework
https://github.com/microsoft/agent-framework

CrewAI
https://github.com/crewAIInc/crewAI

LangGraph
https://github.com/langchain-ai/langgraph

Also investigate AutoGen, OpenHands, OpenClaw, and other relevant maintained open-source multi-agent systems.

For each repository:

Verify that it exists.

Determine its current maintenance status.

Inspect its license and reuse restrictions.

Review source code and documentation.

Identify architectural components.

Analyze agent-to-agent communication.

Identify messaging protocols.

Examine agent identity and discovery.

Analyze message routing and persistence.

Investigate task delegation and orchestration.

Review APIs and integration capabilities.

Examine tool execution.

Evaluate security and permissions.

Identify scalability limitations.

Determine local deployment requirements.

Identify legally reusable components and architectural patterns.

Do not rely solely on README claims.

Inspect implementation files where possible.

Respect software licenses and intellectual property restrictions. Do not copy protected code without appropriate authorization.
Required research outcome
Recommend one of three approaches:
Option A: Fork and customize an existing project.
Option B: Combine compatible open-source components.
Option C: Build our own modular platform using researched architectural patterns.

Compare these approaches on ownership, extensibility, security, complexity, performance, maintainability, and estimated development effort.


⸻

3. Platform Architecture
Design the platform around independent, replaceable components.

Required layers:

Human-facing dashboard

Authentication and authorization

Agent registry

AI provider adapter layer

Real-time messaging system

Agent orchestration engine

Task scheduling and delegation

Shared context and memory

Tool and MCP integration

Sandboxed execution environment

Project and artifact management

Monitoring and audit logging

Human approval system

External client integration interfaces

The messaging layer must be independent of AI providers.

Agents must communicate through a standardized internal messaging protocol.

Avoid vendor lock-in.


⸻

4. AI Provider Integration
Support:

Anthropic Claude

OpenAI GPT models

xAI Grok

Google Gemini

Local models through Ollama

Additional providers through extensible adapters

Each adapter should normalize supported capabilities:

Message generation

Streaming

Tool calling

Structured output

Context management

Error handling

Token accounting

Cost estimation

Authentication

Provider availability

Do not assume every provider supports identical features.

Implement capability discovery and configurable fallback behavior.

Multiple agents must be able to use the same model or different models simultaneously.

Use official provider APIs and supported integrations.

Do not confuse consumer chat applications with API access.


⸻

5. Multi-AI Chatroom
Build a real-time web application combining the usability of ChatGPT, the collaboration features of Discord, and the monitoring capabilities of a development dashboard.
Left Sidebar
Projects

Chatrooms

Agent directory

Active workflows

Task history

Saved prompts

Tools and integrations

Settings
Main Chat Interface
Display:

Human messages

AI agent messages

Agent identities

Message timestamps

Direct messages

Group conversations

Task assignments

Tool execution events

Code artifacts

File attachments

Approval requests

Error notifications
Right Sidebar
Display:

Connected agents

Current model assignments

Active tasks

Execution status

Token consumption

Estimated spending

Agent permissions

Workflow progress

Messages must persist across restarts.

Use WebSockets or an appropriate equivalent for real-time updates.

Humans must be able to pause, resume, and intervene in conversations.


⸻

6. Autonomous AI Workforce
Build an orchestration engine allowing AI agents to collaborate on complex tasks.

Example human request:

“Build a new application dashboard.”

The coordinator should:

Analyze the request.

Create a project plan.

Break the project into tasks.

Assign tasks to appropriate agents.

Coordinate communication.

Monitor progress.

Request reviews.

Execute authorized tests.

Consolidate results.

Present deliverables for approval.

Support sequential, parallel, hierarchical, and event-driven workflows.
Required controls
Configurable maximum conversation turns

Configurable execution duration

Token and API budgets

Task cancellation

Retry limits

Delegation depth limits

Cycle detection

Deadlock prevention

Error recovery

Human intervention

Explicit completion criteria

Prevent infinite conversations and uncontrolled resource consumption.


⸻

7. Customizable AI Agents
Create an agent registry with configurable profiles.

Initial agent templates:
Coordinator Agent: Manages assignments, scheduling, communication, and workflow progress.
Architect Agent: Designs technical architecture and specifications.
Developer Agent: Writes, modifies, and refactors code.
Research Agent: Investigates technologies and documentation.
Reviewer Agent: Evaluates solutions and performs code review.
QA Agent: Creates and executes automated tests.
Security Agent: Reviews vulnerabilities, dependencies, and permissions.
Documentation Agent: Produces technical and operational documentation.

Each agent must support:

Custom identity and name

Custom role

Selected AI provider and model

Custom system prompt

Configurable tools

Permission policies

Memory settings

Spending limits

Collaboration rules

Approval requirements

Allow new agent types without modifying core application code.


⸻

8. Cross-AI Interoperability
This is a critical requirement.
Claude, ChatGPT/OpenAI, Grok, Gemini, and compatible external AI clients must be first-class participants.

Design:

REST APIs

WebSocket interfaces

Webhooks

MCP-compatible tools and servers

Authenticated external client connections

Structured message schemas

Task assignment APIs

Artifact retrieval APIs

External AI clients should be able to:

Authenticate.

Discover authorized agents.

Join permitted conversations.

Read permitted message history.

Send messages.

Receive assignments.

Submit results.

Request authorized tool execution.

Participate in collaborative workflows.

Review project artifacts.

Do not assume that ChatGPT, Claude’s consumer interface, or Grok’s consumer interface can directly access local services.

Research officially supported integration mechanisms.

Where external connectivity is required, propose secure authenticated gateways.

The platform must continue functioning when individual clients disconnect.


⸻

9. Shared Memory and Context
Design persistent memory with clear access boundaries.

Memory categories:

Conversation history

Project memory

Agent-specific memory

Task history

Reusable knowledge

Technical documentation

Code references

Workflow history

Investigate PostgreSQL with pgvector or an appropriate alternative.

Support semantic search, context retrieval, summarization, memory deletion, project isolation, and context-window optimization.

Agents should receive only the information relevant to their assignments and permissions.


⸻

10. Tools, Skills, and MCP Integration
Create a dynamic tool registry supporting:

Native application tools

MCP-compatible tools

External APIs

GitHub integrations

File operations

Sandboxed terminal execution

Browser automation

Database access

Document generation

Testing tools

Custom scripts

Reusable agent skills

Each tool must define:

Identity and description

Input and output schemas

Permission requirements

Execution limits

Audit logging

Error handling

Agents should discover tools based on assigned permissions.

Do not hardcode arbitrary maximum tool counts.


⸻

11. Recommended Technology Stack
Evaluate the following initial stack:
Component
Preferred technology
Frontend

Next.js, React, TypeScript

UI styling

Tailwind CSS

Backend

Python, FastAPI

Database

PostgreSQL

Vector search

pgvector

Real-time communication

WebSockets

Background tasks

Redis and worker framework

Orchestration

LangGraph or custom coordinator

Provider adapters

Official SDKs or compatible abstraction

Local AI

Ollama

Execution isolation

Docker

Deployment

Docker Compose

Version control

Git and GitHub

Testing

Pytest, Vitest, Playwright

Evaluate alternatives based on research.

Do not introduce unnecessary infrastructure or dependencies.

The initial application must run on a local development workstation.

Cloud model APIs may be used, but core application services and data storage should be locally deployable.


⸻

12. Secure Execution and Permissions
Agents may eventually need to:

Read and edit project files

Create Git branches

Write code

Run tests

Install approved dependencies

Execute controlled terminal commands

Inspect documentation

Generate reports

Produce artifacts

Use isolated execution environments.

Implement:

Least-privilege access

Filesystem isolation

Network restrictions

Secrets management

Command auditing

Execution timeouts

Human approval gates

Container resource limits

Git rollback capability

Never grant unrestricted host access by default.
Permission Levels
Level 1 — Research and Planning

Read documentation, inspect repositories, and generate architecture plans.
Level 2 — Development

Create and modify code, install approved dependencies, run tests, and manage development branches.
Level 3 — Controlled Execution

Run sandboxed applications, coordinate agents, and execute authorized workflows.
Level 4 — Privileged Operations

Production deployments, destructive changes, sensitive data access, credential changes, and consequential external actions require explicit authorization.

Permissions must be configurable by agent, project, tool, and environment.


⸻

13. Human Control Dashboard
The human operator must be able to:

Start and stop conversations

Pause agents

Cancel tasks

Approve or reject actions

Change agent assignments

Select models

Set budgets

Inspect tool execution

View message history

Review code changes

Download artifacts

Restart failed workflows

Implement an emergency stop that prevents new agent actions and cancels active work where technically possible.

Approval decisions must be logged.


⸻

14. Multi-Agent Software Development
Support collaboration between Claude Code, OpenAI-powered coding agents, Grok-powered agents, and other compatible development agents.

Required capabilities:

Shared project objectives

Task ownership

Structured handoffs

Shared Git repositories

Isolated branches or worktrees

Code review between agents

Automated tests

Conflict detection

Human approval and merging

Agents must not concurrently modify the same files without coordination.

Support a workflow where one agent implements code, another reviews it, another tests it, and a coordinator manages the process.


⸻

15. Repository Structure
Propose a modular monorepo.

Suggested structure:

multi-ai-command-center/

├── apps/

│   └── web/

├── services/

│   ├── api/

│   ├── orchestrator/

│   ├── messaging/

│   ├── workers/

│   └── execution/

├── packages/

│   ├── provider-adapters/

│   ├── agent-protocol/

│   ├── shared-types/

│   └── ui-components/

├── infrastructure/

│   └── docker/

├── tests/

├── docs/

├── scripts/

├── AGENTS.md

├── CLAUDE.md

├── .env.example

├── docker-compose.yml

└── README.md

Adjust the structure based on actual requirements.

Create:
AGENTS.md: Shared project instructions for compatible coding agents.
CLAUDE.md: Claude Code-specific instructions, workflows, and project conventions.

Keep shared instructions consistent across development agents.


⸻

16. Development Phases
Phase 1 — Technical Discovery
Inspect repositories, compare frameworks, verify licenses, and design the architecture.

Deliver:

Repository analysis

Architecture diagram

Technology decisions

Security model

Development roadmap

Cross-AI interoperability design

Proposed repository structure

Estimated resource requirements
Stop and request my approval before beginning Phase 2.
Phase 2 — Minimum Viable Chatroom
Build:

Local web interface

Backend API

Two different AI provider adapters

Real-time messaging

Conversation persistence

Human participation

Basic coordinator

Demonstrate an actual conversation between two different AI providers.
Phase 3 — Agent Collaboration
Add:

Agent roles

Shared task context

Task assignments

Agent handoffs

Structured collaboration

Completion verification
Phase 4 — Controlled Autonomy
Add:

Task queue

Workflow engine

Sandboxed tools

Automated testing

Code review

Human approvals

Execution audit logs
Phase 5 — Customization
Add:

Agent configuration interface

Custom workflows

Memory management

Provider switching

Project templates

Cost dashboards

Tool and MCP management
Phase 6 — Production Hardening
Add:

Authentication

Role-based access control

Security testing

Recovery procedures

Backup and restore

Performance testing

Observability

Deployment documentation


⸻

17. First Working Demonstration
The initial demonstration must include:

A locally hosted browser interface.

One human operator.

One coordinator.

Two agents connected to different AI providers.

A shared chatroom.

Persistent conversation history.

Agent-to-agent communication.

One collaborative task.

Visible task status.

A human approval checkpoint.
Example
Human: “Create a basic login interface.”

Agent A plans the implementation.

Agent B critiques the plan.

Agent A incorporates feedback.

The coordinator summarizes the result and requests approval.

Use actual model API calls, not simulated agent responses.

Provide evidence through logs and automated tests.


⸻

18. Engineering Standards
Follow these requirements:

TypeScript strict mode where applicable

Python type annotations

Clear service boundaries

Documented interfaces

Automated tests

Environment-based configuration

Minimal necessary dependencies

Appropriate dependency version pinning

Structured logging

Graceful provider failure handling

Secure credential management

Reproducible local setup

Clear architecture documentation

Maintain sufficient documentation for another coding agent to continue development.

Never claim functionality works without testing it.

Do not silently substitute mock implementations for real integrations.


⸻

19. Development Autonomy and Communication
Operate proactively within the authorized development environment.

Do not request approval for every routine research or development action.

Request approval for privileged, destructive, costly, or consequential operations.

Before each major phase:

Explain the proposed work.

Explain architectural reasoning.

Identify affected files and services.

Identify risks.

Define deliverables.

Request approval.

After implementation:

Summarize changes.

List modified files.

Report tests and results.

Identify unresolved issues.

Explain the next milestone.

Do not claim a task is complete until its acceptance criteria have been verified.


⸻

20. Future Extensibility
Design the platform to eventually support:

Additional AI providers

Additional coding agents

Local and remote model execution

GitHub repositories

External applications

MCP servers

Browser automation

Databases and knowledge bases

Business workflows

Custom plugins

Enterprise integrations

Distributed execution across multiple machines

For sensitive business or healthcare integrations, require appropriate authorization, data isolation, auditing, and applicable compliance safeguards.

Do not introduce protected health information into development or testing environments without an approved compliant architecture.


⸻

21. Begin Now — Phase 1
Start with Phase 1: Technical Discovery.

First, inspect AgentPeerChat and the other referenced repositories.

Then produce:

A detailed technical research report.

A comparison of existing solutions.

A recommendation to fork, combine, or build.

A proposed system architecture.

A database and messaging design.

An AI provider integration strategy.

A cross-AI interoperability strategy covering Claude, ChatGPT, Grok, Gemini, and local models.

A security and permissions design.

A phased implementation roadmap.

Initial MVP acceptance tests.

A proposed repository structure.

Estimated hardware and operational requirements.

A list of decisions requiring my input.

Use available authorized tools to conduct actual research.

Clearly distinguish verified findings from architectural recommendations.

If a repository or external resource cannot be accessed, report that limitation rather than inventing findings.
Do not begin Phase 2 until I explicitly approve the architecture.

The ultimate objective is to create a locally controlled, extensible AI collaboration platform that can evolve from a multi-AI chatroom into a customizable autonomous development workforce.

The system must be designed so that Claude, ChatGPT, Grok, Gemini, and future AI systems can collaborate as independent, interchangeable participants.
Begin Phase 1 now.
GitHub - AgenticsWorks/AgentPeerChat: Private messaging for your AI agents. Free to self-host on Cloudflare. Direct chats, groups and a durable inbox.
Private messaging for your AI agents. Free to self-host on Cloudflare. Direct chats, groups and a durable inbox. - AgenticsWorks/AgentPeerChat
 ```
