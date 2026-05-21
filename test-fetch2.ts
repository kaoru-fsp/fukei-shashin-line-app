import { db } from "./src/firebase";
import { collection, getDocs } from "firebase/firestore";

async function run() {
  const snapshot = await getDocs(collection(db, "historyEvents"));
  console.log("Size historyEvents:", snapshot.size);
  if(snapshot.size) {
    console.log(snapshot.docs[0].data());
  }
  process.exit(0);
}
run();
