import { initializeApp } from "firebase/app";
import { getFirestore, collection, getDocs } from "firebase/firestore";
import fs from "fs";

const firebaseConfig = JSON.parse(fs.readFileSync("./src/firebase-applet-config.json", "utf8"));
const app = initializeApp(firebaseConfig);
const db = getFirestore(app, firebaseConfig.firestoreDatabaseId);

async function run() {
  const snapshot = await getDocs(collection(db, "contests"));
  snapshot.forEach(doc => {
    console.log(doc.id, doc.data().Winner, doc.data().WinnerInfo);
  });
  process.exit(0);
}
run();
