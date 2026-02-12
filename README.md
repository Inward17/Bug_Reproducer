# 🚀 AutoRepro – Autonomous Bug Reproduction Agent (AWS)

AutoRepro is an **agentic, serverless AI system** that converts vague bug reports into **verified Python/Selenium reproduction scripts**.

Unlike traditional LLM code generators, AutoRepro:

1. Analyzes the bug report  
2. Generates a reproduction script  
3. Executes it in a secure sandbox  
4. Evaluates runtime results  
5. Refines the script using structured failure feedback  
6. Repeats until the bug is reproduced (or attempts are bounded)

Execution is the **ground truth**.

---

## 🧠 Architecture Overview

- **API Gateway** – Entry point  
- **Step Functions** – Agent controller (reasoning loop)  
- **AWS Bedrock (Claude)** – LLM reasoning engine  
- **Lambda Container** – Secure Selenium execution  
- **DynamoDB** – Job state  
- **S3** – Scripts, logs, screenshots  
- **CloudWatch** – Observability  

The system is fully serverless and stateful, designed around bounded autonomous loops.

---

## 🔁 Agent Workflow

**Analyze → Generate → Execute → Evaluate → Refine → Complete**

Structured runtime failure feedback is injected back into the model, enabling autonomous self-correction.

---

## 🔐 Security

- Sandbox execution in Lambda container  
- Unsafe import detection  
- Execution time limits  
- No AWS credentials inside runtime  

---

## 🎯 Why It Matters

Developers spend massive time reproducing vague bugs.  
AutoRepro automates the entire reproduction cycle — securely, autonomously, and verifiably.

> AutoRepro is not a code generator.  
> It is an autonomous debugging agent.
