import { initializeApp } from "firebase/app";
import { getFirestore, collection, getDocs, query, limit } from "firebase/firestore";

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
const c = collection(db, "contests");
getDocs(query(c, limit(10))).then(snaps => {
  console.log("Empty?", snaps.empty);
  console.log(snaps.docs.map(d => d.data()));
  process.exit(0);
}).catch(e => {
  console.error("Error:", e);
  process.exit(1);
});
