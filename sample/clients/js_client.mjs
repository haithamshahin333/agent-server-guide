// Minimal JS/TS SDK client. Run with: node js_client.mjs [BASE_URL]
// npm install @langchain/langgraph-sdk
import { Client } from "@langchain/langgraph-sdk";

const apiUrl = process.argv[2] ?? "http://127.0.0.1:2024";
const client = new Client({ apiUrl, apiKey: process.env.LANGGRAPH_API_KEY });

const thread = await client.threads.create({ metadata: { user: "demo-js" } });
console.log("thread:", thread.thread_id);

const stream = client.runs.stream(thread.thread_id, "echo", {
  input: { messages: [{ role: "user", content: "hello from the js sdk" }] },
  streamMode: ["updates"],
});
for await (const chunk of stream) {
  console.log("event:", chunk.event, "data:", JSON.stringify(chunk.data));
}

const finalState = await client.runs.wait(thread.thread_id, "echo", {
  input: { messages: [{ role: "user", content: "second turn" }] },
  context: { prefix: "bot", shout: true },
});
console.log("last reply:", finalState.messages.at(-1).content);
