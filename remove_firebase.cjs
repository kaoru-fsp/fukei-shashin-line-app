const fs = require('fs');

let code = fs.readFileSync('src/App.tsx', 'utf-8');

// Remove imports
code = code.replace(/import\s*\{[^}]*\}\s*from\s*["']firebase\/firestore["'];\r?\n/g, '');
code = code.replace(/import\s*\{\s*onAuthStateChanged,\s*User\s*\}\s*from\s*["']firebase\/auth["'];\r?\n/g, '');
code = code.replace(/import\s*\{.*?\}\s*from\s*["']\.\/lib\/firebase["'];\r?\n/g, '');

// Clean up useAuth
code = code.replace(/const useAuth = \(\) => \{[\s\S]*?return \{ user, loading, isAdmin \};\r?\n\};/m, `const useAuth = () => {
  return { user: null, loading: false, isAdmin: false };
};`);

// Replace other Firebase calls with no-ops or default data
// 1. slideshow
code = code.replace(/const slideshowDoc = doc\(db,\s*"settings",\s*"slideshow"\);\s*return onSnapshot\(slideshowDoc,\s*\(snapshot\)\s*=>\s*\{[\s\S]*?\}\);/g, `return () => {};`);
// 2. latest_issue
code = code.replace(/const issueDoc = doc\(db,\s*"settings",\s*"latest_issue"\);\s*return onSnapshot\(issueDoc,\s*\(snapshot\)\s*=>\s*\{[\s\S]*?\}\);/g, `return () => {};`);
// 3. contest
code = code.replace(/return onSnapshot\(doc\(db,\s*"settings",\s*"contest"\),\s*\(snapshot\)\s*=>\s*\{[\s\S]*?\}\);/g, `return () => {};`);
// 4. gallery
code = code.replace(/const galleryDoc = doc\(db,\s*"settings",\s*"gallery"\);\s*return onSnapshot\(galleryDoc,\s*\(snapshot\)\s*=>\s*\{[\s\S]*?\}\);/g, `return () => {};`);
// 5. posts queueing
code = code.replace(/const q = query\(collection\(db,\s*"posts"\),\s*orderBy\("createdAt",\s*"desc"\)\);\s*return onSnapshot\(q,\s*\(snapshot\)\s*=>\s*\{[\s\S]*?\}\);/g, `return () => {};`);

// In Page (e.g. blog load)
code = code.replace(/const unsubscribe = onSnapshot\(q,\s*\(snapshot\)\s*=>\s*\{[\s\S]*?\}\);\s*return unsubscribe;/g, `return () => {};`);
// getDoc, setDoc
code = code.replace(/await getDoc\([^)]+\)/g, `null`);
code = code.replace(/await setDoc\([^)]+\)/g, `undefined`);
code = code.replace(/await deleteDoc\([^)]+\)/g, `undefined`);
code = code.replace(/await updateDoc\([^)]+\)/g, `undefined`);

// Remove handleFirestoreError usages
code = code.replace(/handleFirestoreError\([^)]+\);/g, '');
code = code.replace(/signInWithGoogle\(\);/g, '');
code = code.replace(/logout\(\);/g, '');


fs.writeFileSync('src/App.tsx', code);
