import { db } from "./src/firebase";
import { collection, getDocs } from "firebase/firestore";

async function run() {
  const collectionsToTry = ["contests"];
  for (const c of collectionsToTry) {
    try {
      const snap = await getDocs(collection(db, c));
      console.log(`Collection '${c}': ${snap.size} documents`);
      if(snap.size > 0) {
        snap.forEach(d => console.log("  ", d.id, JSON.stringify(d.data())));
      }
    } catch(e) {
      console.error(`Collection '${c}' error:`, e.message);
    }
  }
  process.exit(0);
}
run();
