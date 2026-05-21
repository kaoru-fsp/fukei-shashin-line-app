# Application Security Specification

## 1. Data Invariants
- **Admins Check**: Only users explicitly existing in `admins/{uid}` can modify settings or write to `posts`.
- **Read Access**:
  - `posts` are public to read.
  - `settings` are public to read.
  - `admins` collection should be strictly limited. Only admins can read the admin collection.
  - `subscribers` collection cannot be read publicly. Only admins can read it.
- **Write Access**:
  - Unauthenticated users: Can ONLY create `subscribers/{id}` under specific conditions (email string and subscribedAt timestamp).
  - Admins: Can create/update/delete `posts` and `settings/*`.
  - Readers: Anyone can update `views` on `posts/{postId}` (increment only).
- **Post Views Action**:
  - Standard users/guests can ONLY update `posts/{postId}` if they only affect `views` and `updatedAt`.
  - `views` must increment appropriately.
  - `updatedAt` must be `request.time`.

## 2. The "Dirty Dozen" Payloads
1. **Unauthenticated Admin Escalation**: Set `isAdmin: true` in user profile. (N/A here, but admin collection spoofing).
2. **Orphaned Post Write**: Create post without valid authorId.
3. **Array Limit Denial of Wallet**: Create a post with 1MB array of tags (if schema supported it, block large inputs).
4. **ID Poisoning**: Inject a 1.5MB junk string as `postId`.
5. **PII Leak**: Read `subscribers` collection as an anonymous user or non-admin.
6. **Shadow Update (Ghost Field)**: Update a post adding `isVerified: true` (only specific keys allowed).
7. **Implicit Relational Read Leak**: Read `admins/{id}` to verify user roles as guest.
8. **Value Poisoning**: Update `views` to a 1MB string instead of number on `posts/{postId}`.
9. **Timestamp Spoofing**: Provide client-side date for `createdAt` on post creation instead of `request.time`.
10. **Unauthenticated Subscriber Write**: Payload includes extra properties like `adminRole: true`.
11. **Settings Overwrite**: Try to delete `settings/slideshow` as guest.
12. **Type Overlap Attack**: Send `settings/latest_issue` payload disguised as `posts`.

## 3. Test Runner
We will construct `firestore.rules.test.ts` to assert against these invariants locally or deploy rules that enforce them.
