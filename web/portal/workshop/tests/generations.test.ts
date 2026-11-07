import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import test from 'node:test';

// Each design generation stays available exactly as reviewed. New work goes in the next candidate.
const originalV4 = {
  "CandidateV4.tsx": "d621189ecc74de2508fd94ed08f8d5ae7e3401dd323514581c33f95d381f5066",
  "V4Profile.tsx": "a24c4daefccfdf3b7a3d53ad45366a7b5d703ec014e60e707e34d71941372cc7",
  "V4Charts.tsx": "2d5f71ed1ea19944d5e1f17340b589167be67efbbc9af504fb5eaa919a71c6ab",
  "V4Map.tsx": "eab1ccaf76001ab018e9e7df93395f95e8eeb5b5725331253e4f47beec37ef59",
  "v4Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b",
  "candidate-v4.css": "1c52d20c76dc42c75ca4f21979540319242bdb9a8f874ac6f938ce7d3469a9e9"
};

test('Candidate v4 remains the original reviewed generation from 5c71ffc1', () => {
  for (const [name, hash] of Object.entries(originalV4)) {
    const contents = readFileSync(new URL('../' + name, import.meta.url));
    assert.equal(createHash('sha256').update(contents).digest('hex'), hash, name + ' changed; make a new candidate instead');
  }
});

const originalV5 = {
  "CandidateV5.tsx": "268420e3997a544f56998ee14059699ca1bf0b3dd25e6a4a46dad7f68d9275f0",
  "V5Profile.tsx": "a4767f5d8aff9bfdb49988c0adcc72c9c15e0ebc3b15af6f04cd3e1076594c02",
  "V5Charts.tsx": "ab71a9b4414afc88c67ecf79bc232ce9f9583d80df1f14987de3475f278e769e",
  "V5Map.tsx": "86a43cd47abc12a4b41eb6f68e3d911ee6c5f77772d89f1260085b97cc9d135f",
  "v5Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b",
  "candidate-v5.css": "7de365c067efcc3a5cfc31e2eaed72a791e481b3742456053b8193f94484d3c7"
};
test("Candidate v5 stays exactly as reviewed at 4aae73a3", () => {
 for (const [name, hash] of Object.entries(originalV5)) assert.equal(createHash("sha256").update(readFileSync(new URL("../" + name, import.meta.url))).digest("hex"), hash, name);
});

const originalV6 = {
  "CandidateV6.tsx": "dadca2d5f0833a014bf1d517a06a25a7bbdd31032616cdc62b0014d432b99d5f",
  "V6Profile.tsx": "6771c5fb510d61b02809351c617071c65ac3811ff783dd07dcc63f7d7a9a76b2",
  "V6Charts.tsx": "d9c4069664a9ade35ec3a63fd31f79a5ad08481324948b786f92dcf30a2a3540",
  "V6Map.tsx": "ab5b4a259b9e27a9688c80b3e9ce707d19c812d86d2b4733444a7c189b82ee05",
  "V6PowerCurve.tsx": "3e7981e7d847f5344c4c0998adc9eeb8ef76e883e0b92c960a22e17895114070",
  "V6Social.tsx": "945b5fcf5944c17943a116d6af98f1796b2766813667ad7052c49161910ce255",
  "v6Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b",
  "v6Model.ts": "143f7785cf7dd45452cd96079070f5016753d715aadeb13ab4a97e05d35d7736",
  "v6Ground.ts": "aa79843f4582aaa99e82797b1483cf099909c767498ed16c46da3006e486b7a4",
  "candidate-v6.css": "2ab7f12e34d700f5fd11bef8b0515fda5bd2e8a30b8a24e3a2fac1859739bb9d"
};
test("Candidate v6 stays exactly as reviewed at 37592e65", () => {
 for (const [name, hash] of Object.entries(originalV6)) assert.equal(createHash("sha256").update(readFileSync(new URL("../" + name, import.meta.url))).digest("hex"), hash, name);
});

const originalV7 = {
  "CandidateV7.tsx": "9fc882b70a151cfac8a4e713b01c0be6161a8f50b257775007d2e0e81290e190",
  "V7Charts.tsx": "da38ae45af4d619fa4d53c3d3b512f5faa7d3060dc56246e5da523a71ea5d7dc",
  "V7ClimbMarks.tsx": "3ce8a3aca99c0784ede6e45373b3e85e6f7160ab57222b8fff04cc5706e0d7b4",
  "V7Map.tsx": "2f848835d2d62f8be20f5393007f0825632331c42adf5d1b99415ba22b140f88",
  "V7MapFrame.tsx": "12422196fe64fa2f7daaf86d343d0fc56f1231409caabdfc9454029ff1666570",
  "V7PowerCurve.tsx": "5cc28b61eb88791c2ca242316b53569abcd3f873a5517256ad5a70572eb9e152",
  "V7Profile.tsx": "3c19661624459672b80cf7d099c580489bbf6c37e75e5d01d34a20b64786737a",
  "V7Social.tsx": "0cd82431daf72d88e601b109d99c2183c3af2997c2b47e5ceeb4983e9e436615",
  "candidate-v7.css": "b23ae62db23f652bc32fb7a46fac3447275335a059efeba4d9efdbf094333687",
  "v7Ground.ts": "7ccde01def08c02119d5bec35500c16f1370c17892ead67a4962b7c9f6e42180",
  "v7Model.ts": "e490565210efbb15a9b5afdf50116560fed11118fe5201d4cdadea7401f538e5",
  "v7Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b"
};
test("Candidate v7 stays exactly as reviewed at 3145bfc2", () => {
 for (const [name, hash] of Object.entries(originalV7)) assert.equal(createHash("sha256").update(readFileSync(new URL("../" + name, import.meta.url))).digest("hex"), hash, name);
});

const originalV8 = {
  "CandidateV8.tsx": "826344ce622617b378c0dda0261f585103e5f0c710d65af3595c21be62475347",
  "V8Charts.tsx": "67737d14dd7791828042e8c36e57a9695b822b5a64a4e60705097fc120d91b7a",
  "V8ClimbMarks.tsx": "1e624b450392290186186b274a2995bcf9e78f8e3db42f96d43de2e1e4bc56f1",
  "V8Economics.tsx": "40783d499805803c40881e0162bc738016a48aa00da93ceb019adea030adbb3a",
  "V8Map.tsx": "954b66703a35745a08cce044bb311f4f5cf7df06638961b364d7a823dd4199e4",
  "V8MapFrame.tsx": "a0cd488f3290e75430cedf903e709536e8bf3631a072bc7f533cbd943cdc60f3",
  "V8PowerCurve.tsx": "199eacb0c978382e4a3d1eab876eed7f83375673fbd41f6bf7bbf41ec4b3e464",
  "V8PowerDistribution.tsx": "039b0cc74968b1f5823dba3d77c524a19fb52e087e42a0a4f65c31ad6e0ab4d1",
  "V8Profile.tsx": "ca6a5b8c33f6e9510f047b6c2b782e59b56271da0c693530187b53a562c118e1",
  "V8RideDetails.tsx": "53d67ff19f07b2b82c83218847bb8dde5e4467951e5db0b51e210b27ee3eee21",
  "V8Social.tsx": "7f865b6963c8cd40ed4123c191fdc6da415cc88718155a3ff3212b99c1803af6",
  "candidate-v8.css": "df86cb194f3b8f6bd92d6006991c7d9e30c34d789b142925770520fbfc3f28d6",
  "v8Example.ts": "22b679e0772ab2cf338a8d7e5a941330d7445785039098783e102f20cc0a4601",
  "v8Ground.ts": "383a3867c106d85b29ebae71fdfe95180476196ad44f7d8c4f704e5d335ead2e",
  "v8Metrics.ts": "29c6d05473331fa7f643d96bd83a664a97922e0e7f6236b3842c6ba23506cfdb",
  "v8Model.ts": "e490565210efbb15a9b5afdf50116560fed11118fe5201d4cdadea7401f538e5",
  "v8Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b"
};
test("Candidate v8 stays exactly as reviewed at 060d05cc", () => {
 for (const [name, hash] of Object.entries(originalV8)) assert.equal(createHash("sha256").update(readFileSync(new URL("../" + name, import.meta.url))).digest("hex"), hash, name);
});

const originalV9 = {
  "CandidateV9.tsx": "906588fce227d90b5d2d5e3195a36e1edd53696626b61d3777088ed198fea503",
  "V9Charts.tsx": "c9374cfc2f827febc284af8a688b05d06317ace2044922dfeede8d316d75e210",
  "V9ClimbMarks.tsx": "c5f2b42236e90c6b03b01c77c46f8d0093850ccb51ad23b6fd9d9dfaa8b3c75d",
  "V9Economics.tsx": "efd4e5961e74b31432e41a0c6537cec95139f9bd0e9921f57e992f97614b6951",
  "V9Map.tsx": "dad4f79a3914309174101ddc1f276c1999da1dfbd792e15b41d2fd6ca2682025",
  "V9MapFrame.tsx": "68061b687f06c623bf8820efe7595d42291b54e0193fb69eec11b309a376f6b1",
  "V9PowerCadence.tsx": "a1a26a4fd9212b127ebc61afbda6ba4b7962a294ae9b7243ea1b753ade4dd430",
  "V9PowerCurve.tsx": "2ba19afd20c3d08f3d9bfeb2dbd5d7e0faeca9d579c76ed048935f2d74857780",
  "V9PowerDistribution.tsx": "851025a58fe46aee487b1ec30fdbc2bdfe29f734f2b86a6451bf9edcf55bc1d7",
  "V9Profile.tsx": "fa2b9adc271c90698ff176c8206a12026f1af8251dec6c3c65b4e00f6ee2956d",
  "V9Relief.tsx": "21525c2fed5e9456685db07ab01d62096ee51e2479b3dd042098b4019474b985",
  "V9RideContext.tsx": "61c4b5d1066e265c80b5890f94daf715ceb4e0d97c6911d2fbdd161e4ede5e26",
  "V9RideDetails.tsx": "306ca8871cb5be209f93416d06d6966cf753fcf302eb1f40b62521fb5270ab36",
  "V9Social.tsx": "f366d3e6255932ec85d507072f2cde996c69e2bca583c7331be3d9c6803d75b7",
  "V9Vault.tsx": "fa17df8fc7a4d391938aeb3990d0f54a04db716dbbf95b5582c75f57774804f5",
  "candidate-v9.css": "589e1ec34891d18c3cebe5e15ff6fb35548eb2dba318138fe4ff4c44681a2562",
  "v9Density.ts": "33ae7528aada5c4952aebd665901b8fa05ab74d630abb7a1ef490c39670cf4a8",
  "v9Example.ts": "8ec7828c3231aa27c2e14ab164845e9aea507b93c721d874ec547accb7edbcd3",
  "v9Ground.ts": "00060f183125eae4b53acf1d2d6f4313704625157ec191fb54c1e9ce7506161f",
  "v9Metrics.ts": "29c6d05473331fa7f643d96bd83a664a97922e0e7f6236b3842c6ba23506cfdb",
  "v9Model.ts": "e490565210efbb15a9b5afdf50116560fed11118fe5201d4cdadea7401f538e5",
  "v9Navigation.ts": "b7395967ae571f7a8311e93098826e78d72c212b5a7113bb27de3f64a146d94b",
  "v9Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b"
};
test("Candidate v9 stays exactly as reviewed at 6548b81b", () => {
 for (const [name, hash] of Object.entries(originalV9)) assert.equal(createHash("sha256").update(readFileSync(new URL("../" + name, import.meta.url))).digest("hex"), hash, name);
});

const originalV10 = {
  "CandidateV10.tsx": "0c7d401dc5af53e9dd55fc56566f98059bcf2a6dd1366c1460ead2cc9fd1e734",
  "V10Charts.tsx": "4a1a0bb5122837c746748eee02e6082dda4555ddadf6a02c56a718ac1bb39c39",
  "V10ClimbMarks.tsx": "9c8bde3780f35414f849cdf463ca752f20e731cd770643f2f192d80093f56b0e",
  "V10Economics.tsx": "477e8eb749f7aa6b227c63e8b0a7f76cf68feec32f4a919eef71ebedb1e6071c",
  "V10Map.tsx": "bba32318e4fdbd1d0bad8e5316e849b45abb87b7e36bdfdc6989f3aa11915ce0",
  "V10MapFrame.tsx": "cb160005f861d84bafd7bc1d49a577c11cb31f521f7189dbfd350be63809f960",
  "V10PowerCadence.tsx": "15a8d6ac4d9e44c79326c12904de76f3ea8dfb82d3768666c54a091b8f280f4d",
  "V10PowerCurve.tsx": "6a947a9eefa7e583b88a0c784afe822289e96f08598b5f19d2d7848cb0532ceb",
  "V10PowerDistribution.tsx": "9bc72d6ad716e977e352a78a8574b8d585d8d02ceec0b8198557284e271c781f",
  "V10Profile.tsx": "00aab1d1c3920baeff957600d6110b0b762bb00bfb40f591424372b3332bd81f",
  "V10Relief.tsx": "d21fdd757d5c3e2372c09560986ab008c5f97c542e2c23251699d769fdaecf55",
  "V10RideContext.tsx": "c883f38cd51be5ffc25dd056332351b8535a00468a13c32da2156db494c3c7dc",
  "V10RideDetails.tsx": "3cd25347c3adc89df8277cca529cf9c5ef54fef9c24a3eee150219f60a6c2ceb",
  "V10Social.tsx": "ae9412144c42b476193bc232d3fe67df915cbfbd20fb550e2193c0267acd230d",
  "V10Vault.tsx": "f35df233d57058fb9f278eb3c7bb02cdf81e3673c27db31159723a0805689814",
  "candidate-v10.css": "271c26b9a4a54feb13948cc7823d28bd78979ec537e5478a4593ef9d30d0e620",
  "v10Density.ts": "22e12b7ea694427b4d97fc467f7bf26515ac3c772579e01a2bf7212f9d7ca75d",
  "v10Example.ts": "428a02294f8569c92234300b3f4983d6e3e1d25843fa840b97b4eb969ac8cc59",
  "v10Ground.ts": "0f8b0f475160dcb56e23e070dfac2a5604e4e03abd6df2b4252296674acda3de",
  "v10Metrics.ts": "29c6d05473331fa7f643d96bd83a664a97922e0e7f6236b3842c6ba23506cfdb",
  "v10Model.ts": "a0104428d735ec1592daab614d8a54a5b128ccbe193b04836fa501fa4dcf35cb",
  "v10Navigation.ts": "c65da9debd2238f3101bb40848af8d547a66570bcd2d8333068d087a375afb5f",
  "v10Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b"
};
test("Candidate v10 stays exactly as reviewed at b330977d", () => {
 for (const [name, hash] of Object.entries(originalV10)) assert.equal(createHash("sha256").update(readFileSync(new URL("../" + name, import.meta.url))).digest("hex"), hash, name);
});

const originalV11 = {
  "CandidateV11.tsx": "828c22fc4c444f606084b01289e5bb91e033a45a2929146993ccd74795859558",
  "V11Charts.tsx": "3e0cab8ccf117ec34b035bc9d9a3e086b68cf54112d6f45a33bc23d16dbfa0c3",
  "V11ClimbMarks.tsx": "2073fa56a92f55bed2e2c12413f876703a3ca6bbbf4c0cd50164dd386772d4f5",
  "V11Economics.tsx": "308065bfc253e16b985a579489ec0d1ed5b7a3da59e6a45a1117e6b186bdf046",
  "V11Map.tsx": "9d571aeec6dee146448fb007bd84aeff3b07efaca99f0f8ca393f16f190ef3ef",
  "V11MapFrame.tsx": "3f8d29b5b173c0b49d30b718de9866d8f37bfcf1f72955215e0194a36c352e5d",
  "V11PowerCadence.tsx": "80cd155874e0bfb3f7b43be8516c6ff2070e8b43bdafaae140f4e41dccc2d3af",
  "V11PowerCurve.tsx": "a4939350baadebdeae6c7cb40e8c1764ecc090a249570d0c644d6b9f9ee824a8",
  "V11PowerDistribution.tsx": "b35e15f99dd180d6a56aa865a0790d824ad677f715a7e4ff9f2102f4a586dc48",
  "V11Profile.tsx": "1e974d719d25df2c6683afcb5aee0382fda95b31bfa08810c6b1d95f1f77134d",
  "V11Relief.tsx": "7f1c29a0362bae1a508088a26451ab5ef6b0c6b5815e573d39c70e4bdcb8fd33",
  "V11RideContext.tsx": "68bf5bd04bce08ed8875376be7a605f71f26744ab59fc58a062671e7ec033b78",
  "V11RideDetails.tsx": "5ac464cf0d862d35c8079d8376ea6a68b8cf8221d9bd5d828caf3c5dd393e5a8",
  "V11Social.tsx": "a4141cf78d763f699aa9faa040137fb70a2e69f5a34b3435d1f97e157327634b",
  "V11Vault.tsx": "ca8d217c057bd6c4f89c4de05f26f33ce34cd55303f4a7cc80c6fc9e5b4c4c30",
  "candidate-v11.css": "7542b44c0774d7705564e12796b284dd15ca4b287c3edf36c47c9a08e2e8e137",
  "v11Density.ts": "22e12b7ea694427b4d97fc467f7bf26515ac3c772579e01a2bf7212f9d7ca75d",
  "v11Example.ts": "80315caf705e1526e668e6b307fd339ef993cf4474138e0717bc314a34269702",
  "v11Ground.ts": "e6962d5611c677f94154a92016fa01b34d108f3af5f82b8bb78c3f18e5fde78f",
  "v11Metrics.ts": "29c6d05473331fa7f643d96bd83a664a97922e0e7f6236b3842c6ba23506cfdb",
  "v11Model.ts": "a0104428d735ec1592daab614d8a54a5b128ccbe193b04836fa501fa4dcf35cb",
  "v11Navigation.ts": "21d8e5e2021e88e949cfa3101dc9474e091f6417c09a6bc8513f2099df1bcd76",
  "v11PowerSelection.ts": "a6ddebba6c201aae970250c25f8c2ded90850d09e2cfa9d32b9495033ad46b9c",
  "v11Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b"
};
test("Candidate v11 stays exactly as reviewed at 75dc068a", () => {
 for (const [name, hash] of Object.entries(originalV11)) assert.equal(createHash("sha256").update(readFileSync(new URL("../" + name, import.meta.url))).digest("hex"), hash, name);
});

const originalV12 = {
  "V12MapFrame.tsx": "64c6f6862f535490a6b74c0d01249df582d8dbf4dafc7011f7fe2ae8539cf981",
  "V12PowerCurve.tsx": "80757f6a84786391f42b288096faf4fb52b0be5dd82b80f3ea98fe4e74ad6caf",
  "V12PowerDistribution.tsx": "fb550e40bc109f0545d436fba578f7bd60db122e8f3515bb3af65325125df198",
  "V12ClimbMarks.tsx": "d05f3a118f9fe518b8550e29edfd3e351840c0c14f6ddbe06104206942639dd5",
  "V12Charts.tsx": "a7c0a306a1d5cf313d3ed4a49eb4342dc0915de0a37ba30ff0742d95ce16bfab",
  "candidate-v12.css": "f79ebba2b1af6e1f344d7941460a074d214c348203697c9c995ac1dac3e3a2af",
  "V12Relief.tsx": "c03f3fbbd4020d00bed567351d608a14c0197dea45f97d0b4d022cee42a6ccd8",
  "v12PowerSelection.ts": "ed375ac27d14bf0b9a1ce86d59e2a244b4ae9fae88bc5e635e9a2220a0062845",
  "V12Profile.tsx": "b4fa0613941ddf57700f2cc52c87cd0c3f2d886912096defa8d0d308a8ceee52",
  "v12Navigation.ts": "ee2aef900365f770315731f4c76e1197bf908096edb5e520bff1439276c9d4c9",
  "v12Density.ts": "22e12b7ea694427b4d97fc467f7bf26515ac3c772579e01a2bf7212f9d7ca75d",
  "V12RideDetails.tsx": "9fd07b64384af3002764b2d453595563a9d4739fdea5d0b212bf17b04c2c34a7",
  "v12Example.ts": "fb6824266d9e434af70245db3ed6d82a778ab9019322f43a15300374fde76ded",
  "v12Ground.ts": "a6d02812e79b58d27c8b5b6e61f6a45c7cf95e7ce3edf5d8860b95978207b3a2",
  "v12Selection.ts": "5f0ad8a7c6e608f183e0dba6b33d1223be2c9b21249b5984cc64367050e90a1b",
  "v12LayoutScenarios.ts": "e32159c1a7cc5ff99bb16853de56ec9043c39cf478850af972d5e27762e99316",
  "V12Social.tsx": "9470931ce1bd5111cc5ad15e228e063887a102082bbc62fd9969f88a98f23d53",
  "V12RideContext.tsx": "89c4cf7c23c178c15ce3e33dec449de33d06f528fca8f900372ceb51c98b10bf",
  "V12PowerCadence.tsx": "8b09f7ff40b35f1970e0ddbf41eb4361ac55a98853084c7a40af6a382a92026f",
  "V12Map.tsx": "acff0884cec280d2881807400046cc11cdf0cea7485d5bce241ec8e209664b82",
  "V12Vault.tsx": "42759d39f42e5b3783f2ad4f964b963e383208c832313b3acb44a9cab596ddcd",
  "v12Model.ts": "a0104428d735ec1592daab614d8a54a5b128ccbe193b04836fa501fa4dcf35cb",
  "V12Economics.tsx": "dfedd00e8b4865ce7a72bef1ebb35aab31821e3fb09a2192712a6a70c4256d5e",
  "CandidateV12.tsx": "75528fccd8b51273126317c65b85167ac74ae9443497670886627b45b110a862",
  "v12Metrics.ts": "29c6d05473331fa7f643d96bd83a664a97922e0e7f6236b3842c6ba23506cfdb"
};
test("Candidate v12 stays exactly as accepted at 534641ac", () => {
 for (const [name, hash] of Object.entries(originalV12)) assert.equal(createHash("sha256").update(readFileSync(new URL("../" + name, import.meta.url))).digest("hex"), hash, name);
});
