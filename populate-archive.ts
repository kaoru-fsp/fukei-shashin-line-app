import { initializeApp } from "firebase/app";
import { getFirestore, collection, getDocs, query, limit, addDoc } from "firebase/firestore";

const firebaseConfig = {
  apiKey: "AIzaSyAn4I5XBMPzggAXM0FsTZH9Ilxx96mZQe8",
  authDomain: "gen-lang-client-0328956131.firebaseapp.com",
  projectId: "gen-lang-client-0328956131",
  storageBucket: "gen-lang-client-0328956131.firebasestorage.app",
  messagingSenderId: "529174988876",
  appId: "1:529174988876:web:82e6d0595ce23fd19e4ce9"
};

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);

async function run() {
  const newsCol = collection(db, "news");
  const archiveCol = collection(db, "archive");
  
  const snaps = await getDocs(query(newsCol, limit(20)));
  for (const doc of snaps.docs) {
    const data = doc.data();
    await addDoc(archiveCol, {
      ...data,
      archivedAt: Date.now()
    });
  }
  console.log("Archive populated");
  process.exit(0);
}
run();
