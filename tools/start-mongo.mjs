import { MongoMemoryServer } from "mongodb-memory-server";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const dbPath = path.join(process.env.TEMP || "/tmp", "brand-memory-os-mongo");
await mkdir(dbPath, { recursive: true });

const mongod = await MongoMemoryServer.create({
  instance: { port: 27017, dbName: "brand_memory_os", dbPath },
});

console.log(`MongoDB ready at ${mongod.getUri()}`);
console.log("Leave this terminal open while you preview the app.");

const stop = async () => {
  await mongod.stop();
  process.exit(0);
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
await new Promise(() => {});
