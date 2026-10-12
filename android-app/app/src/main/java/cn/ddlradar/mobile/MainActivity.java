package cn.ddlradar.mobile;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.text.TextUtils;
import android.view.View;
import android.view.WindowInsets;
import android.view.MotionEvent;
import android.view.VelocityTracker;
import android.view.ViewConfiguration;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONObject;
import org.json.JSONArray;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.ByteArrayInputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Locale;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.Collections;
import java.util.HashSet;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.Instant;
import java.time.YearMonth;
import java.time.format.DateTimeFormatter;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

public final class MainActivity extends Activity {
    private static final int PICK_AVATAR = 41;
    private static final String PROFILE_PREFS = "profile";
    private static final String HOME = "file:///android_asset/index.html";
    private static final String MOOC_CHECK = "https://www.icourse163.org/home.htm#/home/course";
    private static final String MOOC_LOGIN = MOOC_CHECK;
    private static final String YANHE_LOGIN = "https://aita.yanhekt.cn/workbenchAi?tenant_code=21";
    private static final String YANHE_CHECK = "https://aita.yanhekt.cn/personal/courseapi/"
            + "vlabpassportapi/v1/account-profile/course?nowpage=1&per-page=1";
    private static final String ZHIYUAN_LOGIN = "https://zy-eclass.bit.edu.cn/";
    private static final String ZHIYUAN_CHECK =
            "https://zy-eclass.bit.edu.cn/api/todos?no-intercept=true";

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Set<String> requestTrace = new LinkedHashSet<>();
    private WebView webView;
    private TextView statusText;
    private Button confirmButton;
    private Button syncButton;
    private Button authConfirmButton;
    private TextView authStatusText;
    private View authBar;
    private View accountPanel;
    private View settingsPanel;
    private ImageView profileAvatar;
    private ImageView accountAvatar;
    private TextView profileTitle;
    private EditText nameInput;
    private CheckBox moocCheck;
    private CheckBox yanheCheck;
    private CheckBox zhiyuanCheck;
    private CheckBox autoSyncCheck;
    private CheckBox deadlineReminderCheck;
    private EditText accountNameInput;
    private EditText accountPasswordInput;
    private View drawerScrim;
    private View topBar;
    private View bottomBar;
    private View accountManagePanel;
    private View profilePanel;
    private ImageView personalAvatar;
    private EditText profileAccountNameInput;
    private EditText profilePasswordInput;
    private View edgeHandle;
    private ProgressBar syncProgress;
    private TextView drawerAccountSummary;
    private LinearLayout accountList;
    private TextView currentAccountText;
    private String activeAccount = "default";
    private float gestureDownX;
    private float gestureDownY;
    private boolean drawerGestureCandidate;
    private boolean drawerDragging;
    private boolean drawerInitiallyOpen;
    private int touchSlop;
    private VelocityTracker drawerVelocity;
    private RadarSync.Result lastResult;
    private final Map<String, RadarSync.Result> accountResults = new LinkedHashMap<>();
    private final Set<String> unverifiedSessions =
            Collections.synchronizedSet(new HashSet<>());
    private SessionVault vault;
    private Platform currentPlatform;
    private boolean moocCourseMode;
    private String mobileUserAgent;
    private String activeUserAgent;
    private volatile String moocCsrfKey;
    private Future<?> syncFuture;
    private volatile boolean cookieRestoreInProgress;
    private volatile boolean authenticationSaveInProgress;
    private boolean deadlineWindowShown;
    private String currentSection = "tasks";
    private static final String DESKTOP_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            + "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 "
            + "DDLRadar/0.1";

    private enum Platform {
        MOOC("MOOC", MOOC_LOGIN, MOOC_CHECK),
        YANHE("延河课堂", YANHE_LOGIN, YANHE_CHECK),
        ZHIYUAN("智园课堂", ZHIYUAN_LOGIN, ZHIYUAN_CHECK);

        final String title;
        final String loginUrl;
        final String checkUrl;

        Platform(String title, String loginUrl, String checkUrl) {
            this.title = title;
            this.loginUrl = loginUrl;
            this.checkUrl = checkUrl;
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        vault = new SessionVault(this);
        webView = findViewById(R.id.webView);
        statusText = findViewById(R.id.statusText);
        confirmButton = findViewById(R.id.confirmButton);
        syncButton = findViewById(R.id.syncButton);
        authConfirmButton = findViewById(R.id.authConfirmButton);
        authStatusText = findViewById(R.id.authStatusText);
        authBar = findViewById(R.id.authBar);
        accountPanel = findViewById(R.id.accountPanel);
        settingsPanel = findViewById(R.id.settingsPanel);
        profileAvatar = findViewById(R.id.profileAvatar);
        accountAvatar = findViewById(R.id.accountAvatar);
        profileTitle = findViewById(R.id.profileTitle);
        nameInput = findViewById(R.id.nameInput);
        moocCheck = findViewById(R.id.moocCheck);
        yanheCheck = findViewById(R.id.yanheCheck);
        zhiyuanCheck = findViewById(R.id.zhiyuanCheck);
        autoSyncCheck = findViewById(R.id.autoSyncCheck);
        deadlineReminderCheck = findViewById(R.id.deadlineReminderCheck);
        accountNameInput = findViewById(R.id.accountNameInput);
        accountPasswordInput = findViewById(R.id.accountPasswordInput);
        drawerScrim = findViewById(R.id.drawerScrim);
        accountList = findViewById(R.id.accountList);
        currentAccountText = findViewById(R.id.currentAccountText);
        topBar = findViewById(R.id.topBar);
        bottomBar = findViewById(R.id.bottomBar);
        accountManagePanel = findViewById(R.id.accountManagePanel);
        profilePanel = findViewById(R.id.profilePanel);
        personalAvatar = findViewById(R.id.personalAvatar);
        profileAccountNameInput = findViewById(R.id.profileAccountNameInput);
        profilePasswordInput = findViewById(R.id.profilePasswordInput);
        edgeHandle = findViewById(R.id.edgeHandle);
        syncProgress = findViewById(R.id.syncProgress);
        touchSlop = ViewConfiguration.get(this).getScaledTouchSlop();
        drawerAccountSummary = findViewById(R.id.drawerAccountSummary);
        findViewById(R.id.rootView).setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(0, insets.getSystemWindowInsetTop(), 0,
                    insets.getSystemWindowInsetBottom());
            return insets;
        });
        configureWebView();

        findViewById(R.id.moocButton).setOnClickListener(view -> openLogin(Platform.MOOC));
        findViewById(R.id.yanheButton).setOnClickListener(view -> openLogin(Platform.YANHE));
        findViewById(R.id.zhiyuanButton).setOnClickListener(view -> openLogin(Platform.ZHIYUAN));
        findViewById(R.id.homeButton).setOnClickListener(view -> showPlatformSettings());
        findViewById(R.id.copyDiagnosticsButton).setOnClickListener(
                view -> copyRequestDiagnostics());
        confirmButton.setOnClickListener(view -> confirmAuthentication());
        authConfirmButton.setOnClickListener(view -> confirmAuthentication());
        findViewById(R.id.authBackButton).setOnClickListener(view -> showPlatformSettings());
        syncButton.setOnClickListener(view -> syncData());
        findViewById(R.id.tasksTab).setOnClickListener(view -> showTasks());
        findViewById(R.id.calendarTab).setOnClickListener(view -> showCalendar());
        findViewById(R.id.coursesTab).setOnClickListener(view -> showCourses());
        findViewById(R.id.menuButton).setOnClickListener(view -> showHome());
        drawerScrim.setOnClickListener(view -> closeDrawer());
        findViewById(R.id.platformSettingsButton).setOnClickListener(
                view -> showPlatformSettings());
        findViewById(R.id.settingsBackButton).setOnClickListener(view -> leavePlatformSettings());
        findViewById(R.id.avatarButton).setOnClickListener(view -> chooseAvatar());
        findViewById(R.id.saveProfileButton).setOnClickListener(view -> saveProfile());
        findViewById(R.id.accountSwitchButton).setOnClickListener(view -> switchAccount());
        findViewById(R.id.accountRebuildButton).setOnClickListener(view -> rebuildAccount());
        findViewById(R.id.accountDeleteButton).setOnClickListener(view -> confirmDeleteAccount());
        findViewById(R.id.clearMoocButton).setOnClickListener(view -> confirmClearPlatform(Platform.MOOC));
        findViewById(R.id.clearYanheButton).setOnClickListener(view -> confirmClearPlatform(Platform.YANHE));
        findViewById(R.id.clearZhiyuanButton).setOnClickListener(view -> confirmClearPlatform(Platform.ZHIYUAN));
        findViewById(R.id.accountManageButton).setOnClickListener(view -> showAccountManager());
        findViewById(R.id.accountManageBackButton).setOnClickListener(view -> leaveAccountManager());
        findViewById(R.id.profileManageButton).setOnClickListener(view -> showProfile());
        findViewById(R.id.profileBackButton).setOnClickListener(view -> leaveProfile());
        deadlineReminderCheck.setOnCheckedChangeListener((button, checked) -> {
            getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE).edit()
                    .putBoolean("deadline_reminder", checked).apply();
            if (checked) {
                deadlineWindowShown = false;
                maybeShowDeadlineWindow();
            }
        });
        loadProfile();
        autoSyncCheck.setOnCheckedChangeListener((button, checked) ->
                getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE).edit()
                        .putBoolean("auto_sync", checked).apply());
        showTasks();
        validateSavedSessions();
        if (autoSyncCheck.isChecked() && hasSavedAuthentication()) syncData();
        else maybeShowDeadlineWindow();
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setSupportZoom(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        mobileUserAgent = settings.getUserAgentString() + " DDLRadar/0.1";
        activeUserAgent = mobileUserAgent;
        settings.setUserAgentString(activeUserAgent);
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(webView, true);
        webView.setBackgroundColor(Color.WHITE);
        webView.setFocusable(true);
        webView.setFocusableInTouchMode(true);
        webView.addJavascriptInterface(new LocalStateBridge(), "DDLNative");
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int progress) {
                if (currentPlatform != null && progress < 100) {
                    statusText.setText(getString(
                            R.string.loading_auth, currentPlatform.title, progress));
                }
            }
        });
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return false;
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(
                    WebView view, WebResourceRequest request) {
                recordCandidateRequest(request);
                String url = request.getUrl().toString().toLowerCase(Locale.ROOT);
                String host = request.getUrl().getHost();
                if ((host != null && (host.endsWith("google-analytics.com")
                        || host.endsWith("googletagmanager.com")))
                        || url.contains("/statistics/api/user-visits")) {
                    return new WebResourceResponse(
                            "text/plain", "UTF-8", new ByteArrayInputStream(new byte[0]));
                }
                if (currentPlatform != Platform.YANHE) {
                    return null;
                }
                String accept = request.getRequestHeaders().get("Accept");
                boolean heavyAsset = (accept != null && (
                        accept.startsWith("image/")
                                || accept.contains("font/")
                                || accept.startsWith("video/")
                                || accept.startsWith("audio/")))
                        || url.matches(".*\\.(png|jpe?g|gif|webp|svg|woff2?|ttf|mp4|webm)(\\?.*)?$");
                if (heavyAsset) {
                    return new WebResourceResponse(
                            "text/plain", "UTF-8", new ByteArrayInputStream(new byte[0]));
                }
                return null;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                if (currentPlatform != null
                        && !(currentPlatform == Platform.MOOC && moocCourseMode)) {
                    statusText.setText(getString(R.string.auth_instructions, currentPlatform.title));
                    authStatusText.setText(getString(
                            R.string.auth_instructions, currentPlatform.title));
                    confirmButton.setVisibility(View.VISIBLE);
                    authConfirmButton.setVisibility(View.VISIBLE);
                }
            }
        });
    }

    private void openLogin(Platform platform) {
        if (cookieRestoreInProgress || authenticationSaveInProgress) {
            Toast.makeText(this, "正在处理登录状态，请稍候", Toast.LENGTH_SHORT).show();
            return;
        }
        // Cancel large images/scripts still loading from the previous platform first.
        webView.stopLoading();
        currentPlatform = platform;
        webView.setVisibility(View.VISIBLE);
        accountPanel.setVisibility(View.GONE);
        settingsPanel.setVisibility(View.GONE);
        authBar.setVisibility(View.VISIBLE);
        topBar.setVisibility(View.GONE);
        bottomBar.setVisibility(View.GONE);
        edgeHandle.setVisibility(View.GONE);
        moocCourseMode = false;
        activeUserAgent = platform == Platform.MOOC ? DESKTOP_USER_AGENT : mobileUserAgent;
        webView.getSettings().setUserAgentString(activeUserAgent);
        webView.getSettings().setUseWideViewPort(platform == Platform.MOOC);
        webView.getSettings().setLoadWithOverviewMode(platform == Platform.MOOC);
        synchronized (requestTrace) {
            requestTrace.clear();
        }
        // Do not wait for every image/script on the desktop site before allowing confirmation.
        confirmButton.setEnabled(true);
        confirmButton.setVisibility(View.VISIBLE);
        statusText.setText(getString(R.string.opening_auth, platform.title));
        authStatusText.setText(getString(R.string.opening_auth, platform.title));
        authConfirmButton.setEnabled(true);
        webView.requestFocus(View.FOCUS_DOWN);
        webView.loadUrl(platform.loginUrl);
    }

    private void showHome() {
        currentPlatform = null;
        moocCourseMode = false;
        accountPanel.setVisibility(View.VISIBLE);
        drawerScrim.setVisibility(View.VISIBLE);
        accountPanel.setTranslationX(-drawerWidth());
        accountPanel.animate().translationX(0).setDuration(180).start();
        confirmButton.setVisibility(View.GONE);
        statusText.setText(sessionSummary());
        renderAccountList();
    }

    private void closeDrawer() {
        accountPanel.animate().translationX(-drawerWidth())
                .setDuration(160).withEndAction(() -> {
                    accountPanel.setVisibility(View.GONE);
                    drawerScrim.setVisibility(View.GONE);
                    accountPanel.setTranslationX(0);
                }).start();
    }

    private void showPlatformSettings() {
        currentPlatform = null;
        webView.stopLoading();
        closeDrawer();
        settingsPanel.setVisibility(View.VISIBLE);
        authBar.setVisibility(View.GONE);
        topBar.setVisibility(View.GONE);
        bottomBar.setVisibility(View.GONE);
        webView.setVisibility(View.GONE);
        edgeHandle.setVisibility(View.GONE);
        confirmButton.setVisibility(View.GONE);
        authConfirmButton.setVisibility(View.GONE);
        findViewById(R.id.homeButton).setVisibility(View.GONE);
        updatePlatformLabels();
    }

    private void leavePlatformSettings() {
        webView.stopLoading();
        currentPlatform = null;
        settingsPanel.setVisibility(View.GONE);
        topBar.setVisibility(View.VISIBLE);
        bottomBar.setVisibility(View.VISIBLE);
        webView.setVisibility(View.VISIBLE);
        edgeHandle.setVisibility(View.VISIBLE);
        showTasks();
    }

    private void showAccountManager() {
        closeDrawer();
        accountManagePanel.setVisibility(View.VISIBLE);
        settingsPanel.setVisibility(View.GONE);
        topBar.setVisibility(View.GONE);
        bottomBar.setVisibility(View.GONE);
        webView.setVisibility(View.GONE);
        edgeHandle.setVisibility(View.GONE);
        renderAccountList();
    }

    private void leaveAccountManager() {
        accountManagePanel.setVisibility(View.GONE);
        topBar.setVisibility(View.VISIBLE);
        bottomBar.setVisibility(View.VISIBLE);
        webView.setVisibility(View.VISIBLE);
        edgeHandle.setVisibility(View.VISIBLE);
        showTasks();
    }

    private void showProfile() {
        closeDrawer();
        profilePanel.setVisibility(View.VISIBLE);
        settingsPanel.setVisibility(View.GONE);
        accountManagePanel.setVisibility(View.GONE);
        topBar.setVisibility(View.GONE);
        bottomBar.setVisibility(View.GONE);
        webView.setVisibility(View.GONE);
        edgeHandle.setVisibility(View.GONE);
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        nameInput.setText(prefs.getString("nickname_" + accountId(activeAccount),
                activeAccount));
        profileAccountNameInput.setText(activeAccount);
        profilePasswordInput.setText("");
    }

    private void leaveProfile() {
        profilePanel.setVisibility(View.GONE);
        topBar.setVisibility(View.VISIBLE);
        bottomBar.setVisibility(View.VISIBLE);
        webView.setVisibility(View.VISIBLE);
        edgeHandle.setVisibility(View.VISIBLE);
        showTasks();
    }

    private void updatePlatformLabels() {
        moocCheck.setText("MOOC　" + authenticationLabel(Platform.MOOC));
        yanheCheck.setText("延河课堂　" + authenticationLabel(Platform.YANHE));
        zhiyuanCheck.setText("智园课堂　" + authenticationLabel(Platform.ZHIYUAN));
        statusText.setText(sessionSummary());
    }

    private String authenticationLabel(Platform platform) {
        String sessionKey = key(platform);
        if (!vault.contains(sessionKey)) return "未认证";
        return unverifiedSessions.contains(sessionKey) ? "待联网验证 …" : "已认证 ✓";
    }

    private void chooseAvatar() {
        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        intent.addCategory(Intent.CATEGORY_OPENABLE);
        intent.setType("image/*");
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        startActivityForResult(intent, PICK_AVATAR);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != PICK_AVATAR || resultCode != RESULT_OK
                || data == null || data.getData() == null) return;
        Uri uri = data.getData();
        try {
            getContentResolver().takePersistableUriPermission(uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (SecurityException ignored) {
            // Some gallery providers grant access without persistable permissions.
        }
        getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE).edit()
                .putString("avatar_" + accountId(activeAccount), uri.toString()).apply();
        setAvatar(uri);
    }

    private void saveProfile() {
        String nickname = nameInput.getText().toString().trim();
        String newAccount = profileAccountNameInput.getText().toString().trim();
        String newPassword = profilePasswordInput.getText().toString();
        if (nickname.isEmpty()) nickname = "默认用户";
        if (newAccount.isEmpty()) newAccount = activeAccount;
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        String oldAccount = activeAccount;
        if (!newAccount.equals(oldAccount) && newPassword.isEmpty()) {
            Toast.makeText(this, "修改账户名称时请同时设置新密码", Toast.LENGTH_SHORT).show();
            return;
        }
        if (!newAccount.equals(oldAccount)) {
            Set<String> accounts = new java.util.LinkedHashSet<>(prefs.getStringSet(
                    "account_names", java.util.Collections.emptySet()));
            if (accounts.contains(newAccount)) {
                Toast.makeText(this, "该账户名称已经存在，请直接切换账户", Toast.LENGTH_LONG).show();
                return;
            }
            for (Platform platform : Platform.values()) {
                if (vault.contains(keyFor(newAccount, platform))) {
                    Toast.makeText(this, "新账户名称已有认证数据，无法覆盖", Toast.LENGTH_LONG).show();
                    return;
                }
            }
            Map<Platform, String> snapshots = new LinkedHashMap<>();
            try {
                for (Platform platform : Platform.values()) {
                    String saved = vault.get(keyFor(oldAccount, platform));
                    if (saved != null) snapshots.put(platform, saved);
                }
                for (Map.Entry<Platform, String> item : snapshots.entrySet()) {
                    vault.put(keyFor(newAccount, item.getKey()), item.getValue());
                }
            } catch (Exception error) {
                for (Platform platform : Platform.values()) vault.remove(keyFor(newAccount, platform));
                Toast.makeText(this, "账户迁移失败，旧账户保持不变", Toast.LENGTH_LONG).show();
                return;
            }
            accounts.remove(oldAccount);
            accounts.add(newAccount);
            String oldAvatar = prefs.getString("avatar_" + accountId(oldAccount), null);
            String oldCache = prefs.getString("result_cache_" + accountId(oldAccount), null);
            SharedPreferences.Editor rename = prefs.edit().putStringSet("account_names", accounts)
                    .putString("active_account", newAccount)
                    .putString("nickname_" + accountId(newAccount), nickname)
                    .putString("account_password_" + accountId(newAccount),
                            passwordProof(newAccount, newPassword))
                    .remove("nickname_" + accountId(oldAccount))
                    .remove("avatar_" + accountId(oldAccount))
                    .remove("result_cache_" + accountId(oldAccount))
                    .remove("account_password_" + accountId(oldAccount));
            if (oldAvatar != null) rename.putString("avatar_" + accountId(newAccount), oldAvatar);
            if (oldCache != null) rename.putString("result_cache_" + accountId(newAccount), oldCache);
            if (!rename.commit()) {
                for (Platform platform : Platform.values()) vault.remove(keyFor(newAccount, platform));
                Toast.makeText(this, "账户映射保存失败，旧账户保持不变", Toast.LENGTH_LONG).show();
                return;
            }
            for (Platform platform : snapshots.keySet()) vault.remove(keyFor(oldAccount, platform));
            synchronized (accountResults) {
                RadarSync.Result cached = accountResults.remove(oldAccount);
                if (cached != null) accountResults.put(newAccount, cached);
            }
            activeAccount = newAccount;
            accountNameInput.setText(newAccount);
        } else {
            SharedPreferences.Editor edit = prefs.edit()
                    .putString("nickname_" + accountId(activeAccount), nickname);
            if (!newPassword.isEmpty()) edit.putString("account_password_" + accountId(activeAccount),
                    passwordProof(activeAccount, newPassword));
            if (!edit.commit()) {
                Toast.makeText(this, "个人资料保存失败", Toast.LENGTH_LONG).show();
                return;
            }
        }
        profilePasswordInput.setText("");
        profileTitle.setText(nickname);
        renderAccountList();
        Toast.makeText(this, "个人资料已保存", Toast.LENGTH_SHORT).show();
    }

    private void loadProfile() {
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        activeAccount = prefs.getString("active_account", "default");
        migrateLegacyDefaultSessions(activeAccount);
        markAllSavedSessionsUnverified();
        String name = prefs.getString("nickname_" + accountId(activeAccount), activeAccount);
        nameInput.setText(name);
        profileTitle.setText(name);
        profileAccountNameInput.setText(activeAccount);
        String avatar = prefs.getString("avatar_" + accountId(activeAccount),
                prefs.getString("avatar", null));
        if (avatar != null) setAvatar(Uri.parse(avatar));
        moocCheck.setChecked(prefs.getBoolean("sync_mooc", true));
        yanheCheck.setChecked(prefs.getBoolean("sync_yanhe", true));
        zhiyuanCheck.setChecked(prefs.getBoolean("sync_zhiyuan", true));
        autoSyncCheck.setChecked(prefs.getBoolean("auto_sync", true));
        deadlineReminderCheck.setChecked(prefs.getBoolean("deadline_reminder", false));
        accountNameInput.setText(activeAccount);
        ensureAccountRegistered(activeAccount);
        lastResult = loadResultCache(activeAccount);
        if (lastResult != null) accountResults.put(activeAccount, lastResult);
        renderAccountList();
    }

    private void switchAccount() {
        if (cookieRestoreInProgress || authenticationSaveInProgress) {
            Toast.makeText(this, "正在保存或切换登录状态，请稍候", Toast.LENGTH_SHORT).show();
            return;
        }
        String name = accountNameInput.getText().toString().trim();
        String password = accountPasswordInput.getText().toString();
        if (name.isEmpty() || password.isEmpty()) {
            Toast.makeText(this, "请输入账户名称和密码", Toast.LENGTH_SHORT).show();
            return;
        }
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        String id = accountId(name);
        String stored = prefs.getString("account_password_" + id, null);
        String proof = passwordProof(name, password);
        if (stored != null && !stored.equals(proof)) {
            Toast.makeText(this, "账户密码不正确", Toast.LENGTH_SHORT).show();
            return;
        }
        prefs.edit().putString("account_password_" + id, proof)
                .putString("active_account", name).apply();
        ensureAccountRegistered(name);
        activeAccount = name;
        migrateLegacyDefaultSessions(name);
        markSavedSessionsUnverified(name);
        if (syncFuture != null) syncFuture.cancel(true);
        accountPasswordInput.setText("");
        synchronized (accountResults) {
            lastResult = accountResults.get(name);
            if (lastResult == null) {
                lastResult = loadResultCache(name);
                if (lastResult != null) accountResults.put(name, lastResult);
            }
        }
        restoreAccountCookies(name);
        loadActiveAccountAppearance();
        renderAccountList();
    }

    private void confirmClearPlatform(Platform platform) {
        new AlertDialog.Builder(this).setTitle("清除" + platform.title + "认证？")
                .setMessage("只清除当前账户在该平台的登录状态，不删除已缓存的课程和任务。")
                .setNegativeButton("取消", null)
                .setPositiveButton("清除", (dialog, which) -> clearPlatformAuthentication(platform))
                .show();
    }

    private void clearPlatformAuthentication(Platform platform) {
        String sessionKey = keyFor(activeAccount, platform);
        vault.remove(sessionKey);
        unverifiedSessions.remove(sessionKey);
        expireCookies(platform.loginUrl);
        expireCookies(platform.checkUrl);
        if (platform == Platform.MOOC) moocCsrfKey = null;
        updatePlatformLabels();
        renderAccountList();
        statusText.setText(platform.title + "登录状态已清除");
    }

    private void expireCookies(String url) {
        CookieManager manager = CookieManager.getInstance();
        String header = manager.getCookie(url);
        if (TextUtils.isEmpty(header)) return;
        for (String cookie : header.split(";\\s*")) {
            int equals = cookie.indexOf('=');
            if (equals > 0) manager.setCookie(url, cookie.substring(0, equals).trim()
                    + "=; Max-Age=0; Path=/");
        }
        manager.flush();
    }

    private void rebuildAccount() {
        String name = accountNameInput.getText().toString().trim();
        String password = accountPasswordInput.getText().toString();
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        if (name.isEmpty() || password.isEmpty()) {
            Toast.makeText(this, "请输入要重建的账户名称和新密码", Toast.LENGTH_SHORT).show();
            return;
        }
        if (!prefs.getStringSet("account_names", java.util.Collections.emptySet()).contains(name)) {
            Toast.makeText(this, "没有找到该账户", Toast.LENGTH_SHORT).show();
            return;
        }
        new AlertDialog.Builder(this).setTitle("重建账户？")
                .setMessage("将删除该账户的三个平台登录状态、缓存课程与任务、昵称和头像，然后使用新密码创建空账户。")
                .setNegativeButton("取消", null)
                .setPositiveButton("重建", (dialog, which) -> rebuildAccountConfirmed(name, password))
                .show();
    }

    private void rebuildAccountConfirmed(String name, String password) {
        if (name.equals(activeAccount) && syncFuture != null) syncFuture.cancel(true);
        clearAccountData(name, false);
        getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE).edit()
                .putString("account_password_" + accountId(name), passwordProof(name, password))
                .apply();
        ensureAccountRegistered(name);
        accountPasswordInput.setText("");
        if (name.equals(activeAccount)) {
            CookieManager.getInstance().removeAllCookies(null);
            lastResult = null;
            loadActiveAccountAppearance();
            showTasks();
            updatePlatformLabels();
        }
        renderAccountList();
        Toast.makeText(this, "账户已重建，请重新登录平台", Toast.LENGTH_LONG).show();
    }

    private void confirmDeleteAccount() {
        String name = accountNameInput.getText().toString().trim();
        Set<String> accounts = new LinkedHashSet<>(getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE)
                .getStringSet("account_names", java.util.Collections.emptySet()));
        if (name.isEmpty() || !accounts.contains(name)) {
            Toast.makeText(this, "没有找到要删除的账户", Toast.LENGTH_SHORT).show();
            return;
        }
        new AlertDialog.Builder(this).setTitle("删除账户 " + name + "？")
                .setMessage("将永久删除该账户的登录状态、密码、个人资料和缓存数据。")
                .setNegativeButton("取消", null)
                .setPositiveButton("删除", (dialog, which) -> deleteAccountConfirmed(name))
                .show();
    }

    private void deleteAccountConfirmed(String name) {
        boolean deletingActive = name.equals(activeAccount);
        if (deletingActive && syncFuture != null) syncFuture.cancel(true);
        clearAccountData(name, true);
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        Set<String> accounts = new LinkedHashSet<>(prefs.getStringSet(
                "account_names", java.util.Collections.emptySet()));
        if (accounts.isEmpty()) {
            accounts.add("default");
            prefs.edit().putStringSet("account_names", accounts)
                    // The replacement account has no preset password. Its first successful
                    // sign-in initializes the password proof through switchAccount().
                    .remove("account_password_" + accountId("default")).apply();
        }
        if (deletingActive) {
            activeAccount = accounts.iterator().next();
            prefs.edit().putString("active_account", activeAccount).apply();
            synchronized (accountResults) {
                lastResult = accountResults.get(activeAccount);
                if (lastResult == null) lastResult = loadResultCache(activeAccount);
            }
            restoreAccountCookies(activeAccount);
            loadActiveAccountAppearance();
            showTasks();
        }
        accountNameInput.setText(activeAccount);
        accountPasswordInput.setText("");
        renderAccountList();
        Toast.makeText(this, "账户 " + name + " 已删除，无法恢复", Toast.LENGTH_LONG).show();
    }

    private void clearAccountData(String name, boolean removeRegistration) {
        for (Platform platform : Platform.values()) vault.remove(keyFor(name, platform));
        synchronized (accountResults) { accountResults.remove(name); }
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        String id = accountId(name);
        SharedPreferences.Editor editor = prefs.edit().remove("result_cache_" + id)
                .remove("nickname_" + id).remove("avatar_" + id)
                .remove("account_password_" + id);
        if (removeRegistration) {
            Set<String> accounts = new LinkedHashSet<>(prefs.getStringSet(
                    "account_names", java.util.Collections.emptySet()));
            accounts.remove(name);
            editor.putStringSet("account_names", accounts);
        }
        editor.apply();
    }

    private void loadActiveAccountAppearance() {
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        String nickname = prefs.getString("nickname_" + accountId(activeAccount), activeAccount);
        nameInput.setText(nickname);
        profileTitle.setText(nickname);
        profileAccountNameInput.setText(activeAccount);
        String avatar = prefs.getString("avatar_" + accountId(activeAccount), null);
        if (avatar != null) setAvatar(Uri.parse(avatar));
        else {
            profileAvatar.setImageResource(R.drawable.avatar);
            accountAvatar.setImageResource(R.drawable.avatar);
            personalAvatar.setImageResource(R.drawable.avatar);
        }
    }

    private static String accountId(String name) {
        return digest("account:" + name).substring(0, 16);
    }

    private static String passwordProof(String name, String password) {
        return digest("ddl-radar:" + name + ":" + password);
    }

    private static String digest(String value) {
        try {
            byte[] data = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder output = new StringBuilder();
            for (byte item : data) output.append(String.format(Locale.ROOT, "%02x", item));
            return output.toString();
        } catch (Exception error) {
            throw new IllegalStateException(error);
        }
    }

    private void ensureAccountRegistered(String name) {
        SharedPreferences prefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        Set<String> accounts = new java.util.LinkedHashSet<>(
                prefs.getStringSet("account_names", java.util.Collections.emptySet()));
        accounts.add(name);
        prefs.edit().putStringSet("account_names", accounts).apply();
    }

    private void renderAccountList() {
        if (accountList == null) return;
        accountList.removeAllViews();
        currentAccountText.setText("当前账户：" + activeAccount);
        drawerAccountSummary.setText("当前账户：" + activeAccount);
        SharedPreferences profilePrefs = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE);
        profileTitle.setText(profilePrefs.getString("nickname_" + accountId(activeAccount),
                activeAccount));
        Set<String> accounts = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE)
                .getStringSet("account_names", java.util.Collections.singleton("default"));
        for (String account : accounts) {
            Button button = new Button(this);
            button.setAllCaps(false);
            StringBuilder state = new StringBuilder();
            appendAccountState(state, account, Platform.MOOC, "MOOC");
            appendAccountState(state, account, Platform.YANHE, "延河");
            appendAccountState(state, account, Platform.ZHIYUAN, "智园");
            button.setText((account.equals(activeAccount) ? "当前｜" : "") + account
                    + "｜" + (state.length() == 0 ? "未登录平台" : state.toString().trim()));
            button.setOnClickListener(view -> {
                accountNameInput.setText(account);
                accountPasswordInput.requestFocus();
                Toast.makeText(this, "请输入该账户密码后切换", Toast.LENGTH_SHORT).show();
            });
            accountList.addView(button, new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, 44));
        }
    }

    private void restoreAccountCookies(String name) {
        cookieRestoreInProgress = true;
        CookieManager manager = CookieManager.getInstance();
        manager.removeAllCookies(removed -> {
            int restored = 0;
            for (Platform platform : Platform.values()) {
                try {
                    String encrypted = vault.get(keyFor(name, platform));
                    if (encrypted == null) continue;
                    JSONObject cookies = new JSONObject(encrypted).optJSONObject("cookies");
                    if (cookies == null) continue;
                    java.util.Iterator<String> urls = cookies.keys();
                    while (urls.hasNext()) {
                        String url = urls.next();
                        String header = cookies.optString(url);
                        for (String cookie : header.split(";\\s*")) {
                            if (!cookie.isBlank() && cookie.contains("=")) {
                                manager.setCookie(url, cookie);
                            }
                        }
                    }
                    restored++;
                } catch (Exception ignored) { }
            }
            manager.flush();
            int count = restored;
            runOnUiThread(() -> {
                cookieRestoreInProgress = false;
                updatePlatformLabels();
                Toast.makeText(this, count == 0
                                ? "已切换到 " + name + "，该账户尚未登录平台"
                                : "已切换到 " + name + "，恢复了 " + count + " 个平台状态",
                        Toast.LENGTH_LONG).show();
                validateSavedSessions();
            });
        });
    }

    @Override
    public boolean dispatchTouchEvent(MotionEvent event) {
        int action = event.getActionMasked();
        float density = getResources().getDisplayMetrics().density;
        if (action == MotionEvent.ACTION_DOWN) {
            gestureDownX = event.getRawX();
            gestureDownY = event.getRawY();
            drawerInitiallyOpen = accountPanel.getVisibility() == View.VISIBLE;
            drawerGestureCandidate = edgeHandle.getVisibility() == View.VISIBLE
                    && (drawerInitiallyOpen || gestureDownX < 64 * density);
            drawerDragging = false;
            if (drawerVelocity != null) drawerVelocity.recycle();
            drawerVelocity = VelocityTracker.obtain();
            drawerVelocity.addMovement(event);
        } else if (drawerGestureCandidate && action == MotionEvent.ACTION_MOVE) {
            drawerVelocity.addMovement(event);
            float dx = event.getRawX() - gestureDownX;
            float dy = Math.abs(event.getRawY() - gestureDownY);
            if (!drawerDragging && dy > touchSlop && dy > Math.abs(dx) * 1.25f) {
                drawerGestureCandidate = false;
                drawerVelocity.recycle();
                drawerVelocity = null;
                return super.dispatchTouchEvent(event);
            }
            if (!drawerDragging && Math.abs(dx) > touchSlop
                    && Math.abs(dx) > dy * 1.15f
                    && ((drawerInitiallyOpen && dx < 0) || (!drawerInitiallyOpen && dx > 0))) {
                drawerDragging = true;
                MotionEvent cancel = MotionEvent.obtain(event);
                cancel.setAction(MotionEvent.ACTION_CANCEL);
                super.dispatchTouchEvent(cancel);
                cancel.recycle();
                accountPanel.animate().cancel();
                accountPanel.setVisibility(View.VISIBLE);
                drawerScrim.setVisibility(View.VISIBLE);
                if (!drawerInitiallyOpen) {
                    accountPanel.setTranslationX(-drawerWidth());
                    statusText.setText(sessionSummary());
                    renderAccountList();
                }
            }
            if (drawerDragging) {
                float base = drawerInitiallyOpen ? 0 : -drawerWidth();
                accountPanel.setTranslationX(Math.max(-drawerWidth(), Math.min(0, base + dx)));
                drawerScrim.setAlpha(0.55f * (1f + accountPanel.getTranslationX() / drawerWidth()));
                return true;
            }
        } else if (drawerGestureCandidate
                && (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_CANCEL)) {
            drawerVelocity.addMovement(event);
            drawerVelocity.computeCurrentVelocity(1000);
            float velocityX = drawerVelocity.getXVelocity();
            boolean open = velocityX > 550 * density
                    || (velocityX >= -550 * density
                    && accountPanel.getTranslationX() > -drawerWidth() * 0.55f);
            drawerVelocity.recycle();
            drawerVelocity = null;
            drawerGestureCandidate = false;
            if (drawerDragging) {
                drawerDragging = false;
                drawerScrim.setAlpha(1f);
                if (open) {
                    accountPanel.animate().translationX(0).setDuration(140).start();
                } else {
                    closeDrawer();
                }
                return true;
            }
        }
        return super.dispatchTouchEvent(event);
    }

    private float drawerWidth() {
        float measured = accountPanel.getWidth();
        return measured > 0 ? measured : 310 * getResources().getDisplayMetrics().density;
    }

    private void setAvatar(Uri uri) {
        profileAvatar.setImageURI(uri);
        accountAvatar.setImageURI(uri);
        personalAvatar.setImageURI(uri);
    }

    private String sessionSummary() {
        StringBuilder result = new StringBuilder("认证状态：");
        for (Platform platform : Platform.values()) {
            result.append(platform.title).append(' ')
                    .append(authenticationLabel(platform)).append("  ");
        }
        return result.toString().trim();
    }

    private void appendAccountState(StringBuilder output, String account,
                                    Platform platform, String title) {
        String sessionKey = keyFor(account, platform);
        if (!vault.contains(sessionKey)) return;
        output.append(title).append(unverifiedSessions.contains(sessionKey) ? "… " : "✓ ");
    }

    private void markAllSavedSessionsUnverified() {
        Set<String> accounts = new LinkedHashSet<>(getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE)
                .getStringSet("account_names", Collections.emptySet()));
        accounts.add(activeAccount);
        for (String account : accounts) {
            markSavedSessionsUnverified(account);
        }
    }

    private void markSavedSessionsUnverified(String account) {
        for (Platform platform : Platform.values()) {
            String sessionKey = keyFor(account, platform);
            if (vault.contains(sessionKey)) unverifiedSessions.add(sessionKey);
        }
    }

    private void confirmAuthentication() {
        if (currentPlatform == null) {
            return;
        }
        if (cookieRestoreInProgress || authenticationSaveInProgress) {
            Toast.makeText(this, "正在处理登录状态，请稍候", Toast.LENGTH_SHORT).show();
            return;
        }
        Platform platform = currentPlatform;
        String account = activeAccount;
        authenticationSaveInProgress = true;
        confirmButton.setEnabled(false);
        authConfirmButton.setEnabled(false);
        statusText.setText(getString(R.string.validating_auth, platform.title));
        authStatusText.setText(getString(R.string.validating_auth, platform.title));
        CookieManager.getInstance().flush();
        executor.execute(() -> validateAndSave(account, platform));
    }

    private void validateAndSave(String account, Platform platform) {
        try {
            Map<String, String> snapshots = cookiesFor(platform);
            String requestCookies = snapshots.get(platform.checkUrl);
            if (requestCookies == null || requestCookies.isBlank()) {
                vault.remove(keyFor(account, platform));
                throw new IllegalStateException("未找到登录 Cookie，请确认已经完成认证");
            }
            // MOOC currently uses several cross-domain cookie names. Requiring the old
            // STUDY_SESS/STUDY_INFO pair rejects valid newer desktop sessions.
            if (platform != Platform.MOOC) {
                Validation result = request(platform.checkUrl, requestCookies);
                if (!result.ok) {
                    vault.remove(keyFor(account, platform));
                    throw new IllegalStateException("接口返回 " + result.status
                            + "，请确认已进入课程页面后重试");
                }
            }
            JSONObject payload = new JSONObject();
            payload.put("platform", platform.name());
            payload.put("saved_at", System.currentTimeMillis());
            payload.put("cookies", new JSONObject(snapshots));
            if (platform == Platform.MOOC && !TextUtils.isEmpty(moocCsrfKey)) {
                payload.put("csrf_key", moocCsrfKey);
            }
            vault.put(keyFor(account, platform), payload.toString());
            unverifiedSessions.remove(keyFor(account, platform));
            runOnUiThread(() -> {
                authenticationSaveInProgress = false;
                if (!account.equals(activeAccount)) return;
                confirmButton.setVisibility(View.GONE);
                confirmButton.setEnabled(true);
                authConfirmButton.setEnabled(true);
                authStatusText.setText(getString(R.string.auth_success, platform.title));
                statusText.setText(getString(R.string.auth_success, platform.title));
                updatePlatformLabels();
            });
        } catch (Exception error) {
            if (vault.contains(keyFor(account, platform))) {
                unverifiedSessions.add(keyFor(account, platform));
            }
            runOnUiThread(() -> {
                authenticationSaveInProgress = false;
                if (!account.equals(activeAccount)) return;
                statusText.setText(getString(
                        R.string.auth_failed, platform.title, error.getMessage()));
                confirmButton.setVisibility(View.VISIBLE);
                confirmButton.setEnabled(true);
                authConfirmButton.setEnabled(true);
                authStatusText.setText(getString(
                        R.string.auth_failed, platform.title, error.getMessage()));
            });
        }
    }


    private Map<String, String> cookiesFor(Platform platform) {
        CookieManager manager = CookieManager.getInstance();
        Map<String, String> result = new LinkedHashMap<>();
        String[] urls;
        if (platform == Platform.YANHE) {
            urls = new String[]{YANHE_LOGIN, YANHE_CHECK, ZHIYUAN_LOGIN};
        } else {
            urls = new String[]{platform.loginUrl, platform.checkUrl};
        }
        for (String url : urls) {
            String cookies = manager.getCookie(url);
            if (cookies != null && !cookies.isBlank()) {
                result.put(url, cookies);
            }
        }
        return result;
    }

    private Validation request(String address, String cookies) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setInstanceFollowRedirects(true);
        connection.setConnectTimeout(15_000);
        connection.setReadTimeout(20_000);
        connection.setRequestProperty("Accept", "application/json,text/html;q=0.9,*/*;q=0.8");
        connection.setRequestProperty("Cookie", cookies);
        connection.setRequestProperty("User-Agent", activeUserAgent);
        int status = connection.getResponseCode();
        String finalUrl = connection.getURL().toString().toLowerCase(Locale.ROOT);
        String contentType = connection.getContentType();
        InputStream stream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
        String body = readAtMost(stream, 4096);
        connection.disconnect();
        String lowerBody = body.toLowerCase(Locale.ROOT);
        boolean looksLikeLogin = body.contains("统一身份认证")
                || lowerBody.contains("forcelogin")
                || lowerBody.contains("login-form")
                || lowerBody.contains("name=\"password\"")
                || finalUrl.contains("/login")
                || finalUrl.contains("/cas/")
                || finalUrl.contains("oauth");
        boolean apiRequest = address.contains("/api/") || address.contains("courseapi/");
        boolean jsonPayload = body.trim().startsWith("{") || body.trim().startsWith("[")
                || (contentType != null && contentType.toLowerCase(Locale.ROOT).contains("json"));
        return new Validation(status, status >= 200 && status < 300 && !looksLikeLogin
                && (!apiRequest || jsonPayload));
    }

    private static String readAtMost(InputStream stream, int limit) throws Exception {
        if (stream == null) {
            return "";
        }
        StringBuilder output = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            int value;
            while (output.length() < limit && (value = reader.read()) != -1) {
                output.append((char) value);
            }
        }
        return output.toString();
    }

    private String key(Platform platform) {
        return keyFor(activeAccount, platform);
    }

    private String keyFor(String account, Platform platform) {
        String base = "session_" + platform.name().toLowerCase(Locale.ROOT);
        return base + "_" + accountId(account);
    }

    private void migrateLegacyDefaultSessions(String account) {
        if (!"default".equals(account)) return;
        for (Platform platform : Platform.values()) {
            String legacyKey = "session_" + platform.name().toLowerCase(Locale.ROOT);
            String isolatedKey = keyFor("default", platform);
            if (!vault.contains(legacyKey) || vault.contains(isolatedKey)) continue;
            try {
                String value = vault.get(legacyKey);
                if (value != null) vault.put(isolatedKey, value);
                vault.remove(legacyKey);
            } catch (Exception ignored) {
                // Keep the legacy value intact when migration cannot be completed safely.
            }
        }
    }

    private void recordCandidateRequest(WebResourceRequest request) {
        if (currentPlatform == null) {
            return;
        }
        String raw = request.getUrl().toString();
        String lower = raw.toLowerCase(Locale.ROOT);
        String host = request.getUrl().getHost();
        if (host == null
                || host.endsWith("google-analytics.com")
                || host.equals("timor.tech")
                || lower.contains("/statistics/api/user-visits")) {
            return;
        }
        if (currentPlatform == Platform.MOOC && TextUtils.isEmpty(moocCsrfKey)) {
            String value = request.getUrl().getQueryParameter("csrfKey");
            if (!TextUtils.isEmpty(value)) {
                moocCsrfKey = value;
            }
        }
        if (!lower.matches(".*(api|course|homework|quiz|exam|test|task|learn|term|todo|assignment).*")) {
            return;
        }
        if (lower.matches(".*\\.(png|jpe?g|gif|webp|svg|css|js|woff2?|ttf)(\\?.*)?$")) {
            return;
        }
        Uri uri = request.getUrl();
        Uri.Builder safe = uri.buildUpon().clearQuery().fragment(null);
        for (String name : uri.getQueryParameterNames()) {
            safe.appendQueryParameter(name, "<value>");
        }
        String line = platformForHost(host) + " " + request.getMethod() + " " + safe;
        synchronized (requestTrace) {
            if (requestTrace.size() < 250) {
                requestTrace.add(line);
            }
        }
    }

    private static String platformForHost(String host) {
        if (host.endsWith("icourse163.org")) {
            return "MOOC";
        }
        if (host.endsWith("zy-eclass.bit.edu.cn")) {
            return "ZHIYUAN";
        }
        if (host.endsWith("yanhekt.cn")) {
            return "YANHE";
        }
        return "EXTERNAL";
    }

    private void copyRequestDiagnostics() {
        StringBuilder output = new StringBuilder("DDL Radar Android request trace v1\n");
        output.append("page=").append(sanitizedPageUrl()).append('\n');
        synchronized (requestTrace) {
            for (String line : requestTrace) {
                output.append(line).append('\n');
            }
        }
        ClipboardManager clipboard =
                (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
        clipboard.setPrimaryClip(ClipData.newPlainText("DDL Radar 请求诊断", output));
        Toast.makeText(this, R.string.diagnostics_copied, Toast.LENGTH_LONG).show();
    }

    private void syncData() {
        if (cookieRestoreInProgress || authenticationSaveInProgress) {
            Toast.makeText(this, "正在处理登录状态，请稍候", Toast.LENGTH_SHORT).show();
            return;
        }
        final String syncAccount = activeAccount;
        syncButton.setEnabled(false);
        syncProgress.setVisibility(View.VISIBLE);
        statusText.setText(R.string.syncing_data);
        getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE).edit()
                .putBoolean("sync_mooc", moocCheck.isChecked())
                .putBoolean("sync_yanhe", yanheCheck.isChecked())
                .putBoolean("sync_zhiyuan", zhiyuanCheck.isChecked()).apply();
        CookieManager manager = CookieManager.getInstance();
        String moocCookie = manager.getCookie("https://www.icourse163.org/");
        String yanheCookie = manager.getCookie("https://aita.yanhekt.cn/");
        String zhiyuanCookie = manager.getCookie("https://zy-eclass.bit.edu.cn/");
        if (TextUtils.isEmpty(moocCookie)) moocCookie = savedCookie(Platform.MOOC,
                "icourse163.org");
        if (TextUtils.isEmpty(yanheCookie)) yanheCookie = savedCookie(Platform.YANHE,
                "yanhekt.cn");
        if (TextUtils.isEmpty(zhiyuanCookie)) zhiyuanCookie = savedCookie(Platform.ZHIYUAN,
                "zy-eclass.bit.edu.cn");
        if (!moocCheck.isChecked()) moocCookie = null;
        if (!yanheCheck.isChecked()) yanheCookie = null;
        if (!zhiyuanCheck.isChecked()) zhiyuanCookie = null;
        final String selectedMoocCookie = moocCookie;
        final String selectedYanheCookie = yanheCookie;
        final String selectedZhiyuanCookie = zhiyuanCookie;
        if (syncFuture != null) syncFuture.cancel(true);
        syncFuture = executor.submit(() -> {
            String csrf = moocCsrfKey;
            if (TextUtils.isEmpty(csrf)) {
                try {
                    String saved = vault.get(keyFor(syncAccount, Platform.MOOC));
                    if (saved != null) csrf = new JSONObject(saved).optString("csrf_key");
                } catch (Exception ignored) {
                    // A corrupt/old snapshot is reported by the platform result below.
                }
            }
            RadarSync.Result result = RadarSync.run(selectedMoocCookie, csrf,
                    selectedYanheCookie, selectedZhiyuanCookie, DESKTOP_USER_AGENT);
            if (Thread.currentThread().isInterrupted()) return;
            result.savedAt = System.currentTimeMillis();
            updateVerificationFromSync(syncAccount, result);
            clearExpiredAuthentication(result, syncAccount);
            result.tasks.sort((a, b) -> a.due.compareTo(b.due));
            int attempted = result.attemptedPlatforms.size();
            int succeeded = result.successfulPlatforms.size();
            boolean usableResult = succeeded > 0 || !result.courses.isEmpty()
                    || !result.tasks.isEmpty();
            if (usableResult) synchronized (accountResults) {
                accountResults.put(syncAccount, result);
            }
            if (usableResult) {
                saveResultCache(syncAccount, result);
            }
            final boolean hasUsableResult = usableResult;
            final int attemptedCount = attempted;
            final int succeededCount = succeeded;
            runOnUiThread(() -> {
                syncButton.setEnabled(true);
                syncProgress.setVisibility(View.GONE);
                if (!syncAccount.equals(activeAccount)) return;
                if (hasUsableResult) lastResult = result;
                currentPlatform = null;
                confirmButton.setVisibility(View.GONE);
                updatePlatformLabels();
                String message;
                if (attemptedCount == 0) {
                    message = "未找到已勾选平台的可用登录状态，数据未更新";
                } else if (succeededCount == attemptedCount && result.errors.isEmpty()) {
                    message = "同步成功：" + succeededCount + " 个平台，"
                            + result.courses.size() + " 门课程，" + result.tasks.size() + " 项任务";
                } else if (succeededCount > 0) {
                    message = "部分同步成功：" + succeededCount + "/" + attemptedCount
                            + " 个平台，" + result.courses.size() + " 门课程，"
                            + result.tasks.size() + " 项任务";
                } else {
                    message = "同步失败，已保留上次缓存";
                }
                if (!result.invalidPlatforms.isEmpty()) message += "；"
                        + result.invalidPlatforms.size() + " 个平台登录已失效";
                statusText.setText(message);
                Toast.makeText(this, message, Toast.LENGTH_LONG).show();
                if (hasUsableResult) {
                    refreshVisibleSection();
                    deadlineWindowShown = false;
                    maybeShowDeadlineWindow();
                }
            });
        });
    }

    private boolean hasSavedAuthentication() {
        return (moocCheck.isChecked() && vault.contains(key(Platform.MOOC)))
                || (yanheCheck.isChecked() && vault.contains(key(Platform.YANHE)))
                || (zhiyuanCheck.isChecked() && vault.contains(key(Platform.ZHIYUAN)));
    }

    private void maybeShowDeadlineWindow() {
        if (deadlineWindowShown || deadlineReminderCheck == null
                || !deadlineReminderCheck.isChecked() || lastResult == null) return;
        Instant now = Instant.now();
        Instant limit = now.plusSeconds(48L * 60L * 60L);
        java.util.List<RadarSync.Task> upcoming = new java.util.ArrayList<>();
        for (RadarSync.Task task : lastResult.tasks) {
            if (task.completed) continue;
            Instant due = parseDeadline(task.due);
            if (due != null && !due.isBefore(now) && !due.isAfter(limit)) upcoming.add(task);
        }
        if (upcoming.isEmpty()) return;
        upcoming.sort((left, right) -> {
            Instant a = parseDeadline(left.due);
            Instant b = parseDeadline(right.due);
            return a == null ? 1 : b == null ? -1 : a.compareTo(b);
        });
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(18), dp(15), dp(18), dp(8));
        content.setBackgroundResource(R.drawable.deadline_alert_background);
        TextView intro = new TextView(this);
        intro.setText("以下任务将在 48 小时内截止：");
        intro.setTextColor(Color.rgb(49, 94, 251));
        intro.setTextSize(14);
        content.addView(intro);
        int count = Math.min(upcoming.size(), 8);
        for (int i = 0; i < count; i++) {
            RadarSync.Task task = upcoming.get(i);
            TextView row = new TextView(this);
            row.setText("\n" + task.title + "\n" + task.course + " · " + task.due);
            row.setTextColor(Color.rgb(24, 32, 43));
            row.setTextSize(14);
            content.addView(row);
        }
        if (upcoming.size() > count) {
            TextView more = new TextView(this);
            more.setText("\n另有 " + (upcoming.size() - count) + " 项，请在待办中查看");
            more.setTextColor(Color.rgb(104, 115, 133));
            content.addView(more);
        }
        deadlineWindowShown = true;
        new AlertDialog.Builder(this)
                .setTitle("临近截止")
                .setView(content)
                .setNegativeButton("关闭提醒", (dialog, which) -> {
                    deadlineReminderCheck.setChecked(false);
                })
                .setPositiveButton("知道了", null)
                .show();
    }

    private static Instant parseDeadline(String raw) {
        if (TextUtils.isEmpty(raw)) return null;
        String value = raw.trim();
        try { return Instant.parse(value); } catch (Exception ignored) { }
        try { return OffsetDateTime.parse(value).toInstant(); } catch (Exception ignored) { }
        try {
            return LocalDateTime.parse(value.replace(' ', 'T'),
                    DateTimeFormatter.ISO_LOCAL_DATE_TIME)
                    .atZone(ZoneId.systemDefault()).toInstant();
        } catch (Exception ignored) { }
        try {
            return LocalDate.parse(value.substring(0, Math.min(10, value.length())))
                    .atTime(23, 59).atZone(ZoneId.systemDefault()).toInstant();
        } catch (Exception ignored) { return null; }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private final class LocalStateBridge {
        @JavascriptInterface
        public void setPriority(String taskKey, String priority) {
            if (taskKey == null || !taskKey.matches("[0-9a-f]{12}")
                    || !("red".equals(priority) || "yellow".equals(priority)
                    || "green".equals(priority) || "blue".equals(priority))) return;
            getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE).edit()
                    .putString("task_priority_" + accountId(activeAccount) + "_" + taskKey,
                            priority).apply();
        }
    }

    private String savedCookie(Platform platform, String hostPart) {
        return savedCookie(activeAccount, platform, hostPart);
    }

    private String savedCookie(String account, Platform platform, String hostPart) {
        try {
            String saved = vault.get(keyFor(account, platform));
            if (saved == null) return null;
            JSONObject cookies = new JSONObject(saved).optJSONObject("cookies");
            if (cookies == null) return null;
            String best = null;
            java.util.Iterator<String> urls = cookies.keys();
            while (urls.hasNext()) {
                String url = urls.next();
                if (!url.contains(hostPart)) continue;
                String value = cookies.optString(url, null);
                if (!TextUtils.isEmpty(value) && (best == null || value.length() > best.length())) {
                    best = value;
                }
            }
            return best;
        } catch (Exception ignored) {
            return null;
        }
    }

    private void validateSavedSessions() {
        final String account = activeAccount;
        executor.execute(() -> {
            boolean changed = false;
            for (Platform platform : Platform.values()) {
                if (!vault.contains(keyFor(account, platform))) continue;
                String host = platform == Platform.MOOC ? "icourse163.org"
                        : platform == Platform.YANHE ? "yanhekt.cn" : "zy-eclass.bit.edu.cn";
                String cookie = savedCookie(account, platform, host);
                if (TextUtils.isEmpty(cookie)) continue;
                try {
                    Validation validation = request(platform.checkUrl, cookie);
                    if (!validation.ok) {
                        vault.remove(keyFor(account, platform));
                        unverifiedSessions.remove(keyFor(account, platform));
                        changed = true;
                    } else if (unverifiedSessions.remove(keyFor(account, platform))) {
                        changed = true;
                    }
                } catch (Exception ignored) {
                    // Offline startup must retain the last known authentication state.
                }
            }
            boolean stateChanged = changed;
            runOnUiThread(() -> {
                if (stateChanged && account.equals(activeAccount)) updatePlatformLabels();
            });
        });
    }

    private void updateVerificationFromSync(String account, RadarSync.Result result) {
        for (Platform platform : Platform.values()) {
            String apiName = platform.name();
            String sessionKey = keyFor(account, platform);
            if (result.successfulPlatforms.contains(apiName)) {
                unverifiedSessions.remove(sessionKey);
            } else if (result.attemptedPlatforms.contains(apiName)
                    && !result.invalidPlatforms.contains(apiName)
                    && vault.contains(sessionKey)) {
                unverifiedSessions.add(sessionKey);
            }
        }
    }

    private void saveResultCache(String account, RadarSync.Result result) {
        try {
            JSONObject root = new JSONObject();
            root.put("saved_at", result.savedAt > 0 ? result.savedAt : System.currentTimeMillis());
            JSONArray courses = new JSONArray();
            for (RadarSync.Course course : result.courses) {
                courses.put(new JSONObject().put("platform", course.platform)
                        .put("name", course.name).put("term", course.term)
                        .put("school", course.school).put("term_id", course.termId)
                        .put("url", course.url).put("remote_id", course.remoteId));
            }
            JSONArray tasks = new JSONArray();
            for (RadarSync.Task task : result.tasks) {
                tasks.put(new JSONObject().put("course", task.course)
                        .put("title", task.title).put("type", task.type)
                        .put("due", task.due).put("completed", task.completed)
                        .put("details", task.details));
            }
            root.put("courses", courses).put("tasks", tasks);
            getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE).edit()
                    .putString("result_cache_" + accountId(account), root.toString()).apply();
        } catch (Exception ignored) {
            // A failed cache write must not invalidate freshly synchronized in-memory data.
        }
    }

    private RadarSync.Result loadResultCache(String account) {
        String saved = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE)
                .getString("result_cache_" + accountId(account), null);
        if (saved == null) return null;
        try {
            JSONObject root = new JSONObject(saved);
            RadarSync.Result result = new RadarSync.Result();
            result.savedAt = root.optLong("saved_at");
            JSONArray courses = root.optJSONArray("courses");
            for (int i = 0; courses != null && i < courses.length(); i++) {
                JSONObject item = courses.optJSONObject(i);
                if (item == null) continue;
                result.courses.add(new RadarSync.Course(item.optString("platform"),
                        item.optString("name"), item.optString("term"),
                        item.optString("school"), item.optLong("term_id"),
                        item.optString("url"), item.optString("remote_id")));
            }
            JSONArray tasks = root.optJSONArray("tasks");
            for (int i = 0; tasks != null && i < tasks.length(); i++) {
                JSONObject item = tasks.optJSONObject(i);
                if (item == null) continue;
                result.tasks.add(new RadarSync.Task(item.optString("course"),
                        item.optString("title"), item.optString("type"),
                        item.optString("due"), item.optBoolean("completed"),
                        item.optString("details")));
            }
            return result;
        } catch (Exception error) {
            getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE).edit()
                    .remove("result_cache_" + accountId(account)).apply();
            return null;
        }
    }

    private void clearExpiredAuthentication(RadarSync.Result result, String account) {
        if (result.invalidPlatforms.contains("MOOC")) {
            vault.remove(keyFor(account, Platform.MOOC));
            unverifiedSessions.remove(keyFor(account, Platform.MOOC));
        }
        if (result.invalidPlatforms.contains("YANHE")) {
            vault.remove(keyFor(account, Platform.YANHE));
            unverifiedSessions.remove(keyFor(account, Platform.YANHE));
        }
        if (result.invalidPlatforms.contains("ZHIYUAN")) {
            vault.remove(keyFor(account, Platform.ZHIYUAN));
            unverifiedSessions.remove(keyFor(account, Platform.ZHIYUAN));
        }
    }

    private void showTasks() {
        currentSection = "tasks";
        accountPanel.setVisibility(View.GONE);
        drawerScrim.setVisibility(View.GONE);
        settingsPanel.setVisibility(View.GONE);
        profilePanel.setVisibility(View.GONE);
        accountManagePanel.setVisibility(View.GONE);
        if (lastResult == null) {
            webView.loadDataWithBaseURL("https://ddlradar.local/", emptyPage(
                    "待办", "打开左上角菜单，在平台与同步中更新数据"),
                    "text/html", "UTF-8", null);
            return;
        }
        webView.loadDataWithBaseURL("https://ddlradar.local/", renderTasks(lastResult,
                        accountId(activeAccount)),
                "text/html", "UTF-8", null);
    }

    private void showCourses() {
        currentSection = "courses";
        profilePanel.setVisibility(View.GONE);
        accountPanel.setVisibility(View.GONE);
        settingsPanel.setVisibility(View.GONE);
        if (lastResult == null) {
            webView.loadDataWithBaseURL("https://ddlradar.local/", emptyPage(
                    "课程", "请先在账户页完成认证并同步"), "text/html", "UTF-8", null);
            return;
        }
        webView.loadDataWithBaseURL("https://ddlradar.local/", renderCourses(lastResult),
                "text/html", "UTF-8", null);
    }

    private void showCalendar() {
        currentSection = "calendar";
        profilePanel.setVisibility(View.GONE);
        accountPanel.setVisibility(View.GONE);
        settingsPanel.setVisibility(View.GONE);
        if (lastResult == null) {
            webView.loadDataWithBaseURL("https://ddlradar.local/", emptyPage(
                    "日历", "请先完成平台认证并同步课程与任务"),
                    "text/html", "UTF-8", null);
            return;
        }
        webView.loadDataWithBaseURL("https://ddlradar.local/", renderCalendar(lastResult,
                        accountId(activeAccount)),
                "text/html", "UTF-8", null);
    }

    private void refreshVisibleSection() {
        if (settingsPanel.getVisibility() == View.VISIBLE
                || accountManagePanel.getVisibility() == View.VISIBLE
                || profilePanel.getVisibility() == View.VISIBLE
                || accountPanel.getVisibility() == View.VISIBLE) return;
        if ("calendar".equals(currentSection)) showCalendar();
        else if ("courses".equals(currentSection)) showCourses();
        else showTasks();
    }

    private static String pageStart(String title) {
        return "<!doctype html><html><head><meta charset='utf-8'>"
                + "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                + "<style>*{box-sizing:border-box}body{margin:0;padding:22px 18px 36px;font:15px/1.5 system-ui;"
                + "color:#18202b;background:#f4f6f8}h1{font-size:26px;letter-spacing:-.5px;margin:5px 0 20px}h2{font-size:17px;margin:24px 2px 10px}"
                + ".card{background:#fff;border:1px solid #e2e7ed;border-radius:12px;padding:15px;margin:9px 0;box-shadow:0 1px 2px #17203608}"
                + ".meta{color:#687385;font-size:13px;margin-top:5px}.tag{color:#315efb;font-weight:700}"
                + ".error{background:#fff5f4;border-color:#f4d3d0;color:#9e332b}.empty{text-align:center;color:#8a94a3;padding:52px 10px}"
                + ".week,.grid{display:grid;grid-template-columns:repeat(7,1fr);text-align:center;gap:7px}"
                + ".week{color:#7d8796;margin-bottom:10px;font-size:12px}.day{min-height:46px;padding:7px 2px;border-radius:9px}"
                + ".today{box-shadow:inset 0 0 0 1.5px #315efb}.selected{background:#eaf0ff;color:#18202b;box-shadow:inset 0 0 0 1.5px #315efb}.dot{display:block;margin:4px auto 0;width:6px;height:6px;border-radius:50%;background:#315efb}"
                + "details summary{list-style:none;cursor:pointer}details summary::-webkit-details-marker{display:none}"
                + ".tree>summary{position:relative;padding-left:27px}.tree>summary:before{content:'›';position:absolute;left:5px;top:50%;transform:translateY(-50%);font-size:23px;color:#315efb;font-weight:700;transition:.15s}.tree[open]>summary:before{transform:translateY(-50%) rotate(90deg)}"
                + ".term-tree{margin-left:11px;border-left:2px solid #dce3ee;padding-left:10px}.course-tree{margin-left:8px}"
                + ".detail{border-top:1px solid #e8ecf1;margin-top:12px;padding-top:12px;color:#596575}.detail select,.detail textarea{border:1px solid #d9e0e8;border-radius:8px;background:#fff;padding:9px;color:#18202b}.levels{display:flex;gap:9px;margin-top:12px}"
                + ".level{width:27px;height:27px;border:0;border-radius:50%}.red{background:#ef5350}.yellow{background:#f5b942}.green{background:#35bd8b}.blue{background:#4e70f5}"
                + ".p-red{border-left:6px solid #ef5350}.p-yellow{border-left:6px solid #f5b942}.p-green{border-left:6px solid #35bd8b}.p-blue{border-left:6px solid #4e70f5}"
                + ".search{width:100%;border:1px solid #e2e7ed;border-radius:10px;background:#fff;padding:13px 14px;font-size:15px;margin-bottom:12px;outline:none}"
                + ".view-select{width:100%;border:1px solid #e2e7ed;border-radius:10px;background:#fff;padding:12px 14px;font-size:14px;color:#374151;margin:-7px 0 18px}"
                + ".task-root{margin:12px 0 21px}.task-root>summary{background:#eaf0ff;border:1px solid #dbe4ff;border-radius:11px;padding:12px 14px 12px 40px}.task-root>summary:before{left:14px}.task-root>summary h2{margin:0;display:inline-block}"
                + ".task-category{margin:9px 0 9px 12px;border-left:2px solid #dce3ee;padding-left:10px}.task-category>summary{padding:8px 8px 8px 32px}.task-category>summary:before{left:8px;font-size:21px}.task-category>summary h3{font-size:15px;margin:0;display:inline-block}"
                + "body.all-tasks .task-root,body.all-tasks .task-category{margin:0;border:0;padding:0}body.all-tasks .task-root>summary,body.all-tasks .task-category>summary{display:none}body.all-tasks .taskgroup{display:block!important}"
                + ".monthbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px}.monthbar button{border:1px solid #e2e7ed;background:#fff;border-radius:9px;padding:9px 14px;font-size:16px;color:#263141}a{color:#315efb;text-decoration:none;font-weight:600}"
                + "</style></head><body><h1>" + escape(title) + "</h1>";
    }

    private static String renderTasks(RadarSync.Result result, String accountNamespace) {
        StringBuilder html = new StringBuilder(pageStart("待办"));
        appendUpdatedAt(html, result);
        if (result.tasks.isEmpty()) html.append("<div class='card'>当前没有读取到待办。</div>");
        html.append("<select id='taskView' class='view-select' onchange='taskView(this.value)'>"
                + "<option value='categorized'>分类显示</option><option value='all'>全部任务</option></select>");
        html.append("<details class='tree task-root' open><summary><h2>未完成</h2></summary>");
        appendTaskGroup(html, "作业", result.tasks, "assignment", "pending");
        appendTaskGroup(html, "测验与考试", result.tasks, "test", "pending");
        html.append("</details><details class='tree task-root' open><summary><h2>已逾期</h2></summary>");
        appendTaskGroup(html, "全部类型", result.tasks, "all", "overdue");
        html.append("</details><details class='tree task-root'><summary><h2>已完成</h2></summary>");
        appendTaskGroup(html, "全部类型", result.tasks, "all", "completed");
        html.append("</details>");
        if (!result.errors.isEmpty()) {
            html.append("<h2>同步告示</h2>");
            for (String error : result.errors) html.append("<div class='card error'>")
                    .append(escape(error)).append("</div>");
        }
        html.append("<script>const rank={red:0,yellow:1,green:2,blue:3},ns='a:")
                .append(escape(accountNamespace)).append(":';"
                + "function sk(k){return ns+k}function taskView(v){document.body.classList.toggle('all-tasks',v==='all');document.querySelectorAll('.task-root,.task-category').forEach(e=>{if(v==='all')e.open=true});localStorage.setItem(sk('task-view'),v)}"
                + "function reorder(){document.querySelectorAll('.taskgroup').forEach(g=>[...g.querySelectorAll('[data-key]')].sort((a,b)=>rank[a.dataset.priority]-rank[b.dataset.priority]).forEach(e=>g.appendChild(e)))}"
                + "document.querySelectorAll('[data-key]').forEach(e=>{let p=localStorage.getItem(sk('urgency:'+e.dataset.key))||'blue';e.dataset.priority=p;e.classList.add('p-'+p);let n=e.querySelector('textarea');n.value=localStorage.getItem(sk('note:'+e.dataset.key))||n.value;let s=localStorage.getItem(sk('state:'+e.dataset.key));if(s){e.querySelector('select').value=s;moveState(e,s)}});reorder();"
                + "function urgency(ev,k,p){ev.preventDefault();ev.stopPropagation();let e=document.querySelector('[data-key=\"'+k+'\"]');e.classList.remove('p-red','p-yellow','p-green','p-blue');e.classList.add('p-'+p);e.dataset.priority=p;localStorage.setItem(sk('urgency:'+k),p);if(window.DDLNative)DDLNative.setPriority(k,p);reorder()}"
                + "function note(k,v){localStorage.setItem(sk('note:'+k),v)}function moveState(e,v){let st=v==='已完成'?'completed':(e.dataset.overdue==='true'?'overdue':'pending'),sel='.taskgroup[data-state=\"'+st+'\"]'+(st==='pending'?'[data-kind=\"'+e.dataset.kind+'\"]':'');let g=document.querySelector(sel);if(g)g.appendChild(e)}function state(k,v){let e=document.querySelector('[data-key=\"'+k+'\"]');localStorage.setItem(sk('state:'+k),v);moveState(e,v);reorder()}let tv=localStorage.getItem(sk('task-view'))||'categorized';document.getElementById('taskView').value=tv;taskView(tv)</script>");
        return html.append("</body></html>").toString();
    }

    private static void appendTaskGroup(StringBuilder html, String title,
                                        java.util.List<RadarSync.Task> tasks,
                                        String kind, String state) {
        String today = LocalDate.now().format(DateTimeFormatter.ISO_LOCAL_DATE);
        boolean wroteTitle = false;
        StringBuilder cards = new StringBuilder();
        for (RadarSync.Task task : tasks) {
            boolean isOverdue = task.due.length() >= 10 && task.due.substring(0, 10).compareTo(today) < 0;
            boolean isAssignment = task.type.contains("作业");
            boolean typeMatches = "all".equals(kind) || ("assignment".equals(kind) == isAssignment);
            boolean stateMatches = "completed".equals(state) ? task.completed
                    : "overdue".equals(state) ? (!task.completed && isOverdue)
                    : (!task.completed && !isOverdue);
            if (!stateMatches || !typeMatches) continue;
            wroteTitle = true;
            String key = digest(task.course + "|" + task.title + "|" + task.due).substring(0, 12);
            cards.append("<details class='card' data-key='").append(key)
                    .append("' data-priority='blue' data-kind='").append(isAssignment ? "assignment" : "test")
                    .append("' data-overdue='").append(isOverdue).append("'><summary><span class='tag'>")
                    .append(escape(task.type)).append("</span> ").append(escape(task.title))
                    .append("<div class='meta'>").append(escape(task.course));
            if (!TextUtils.isEmpty(task.due)) cards.append(" · 截止 ").append(escape(task.due));
            cards.append("</div></summary><div class='detail'>")
                    .append(TextUtils.isEmpty(task.details) ? "暂无平台详情" : escape(task.details))
                    .append("<br><label>状态：<select onchange=\"state('").append(key).append("',this.value)\"><option")
                    .append(task.completed ? "" : " selected").append(">未完成</option><option")
                    .append(task.completed ? " selected" : "").append(">已完成</option></select></label>"
                    + "<br><textarea rows='3' style='width:100%;margin-top:10px' placeholder='编辑任务备注' oninput=\"note('").append(key).append("',this.value)\"></textarea><br>紧急程度："
                    + "<div class='levels'><button class='level red' onclick=\"urgency(event,'").append(key).append("','red')\"></button>"
                    + "<button class='level yellow' onclick=\"urgency(event,'").append(key).append("','yellow')\"></button>"
                    + "<button class='level green' onclick=\"urgency(event,'").append(key).append("','green')\"></button>"
                    + "<button class='level blue' onclick=\"urgency(event,'").append(key).append("','blue')\"></button></div></div></details>");
        }
        html.append("<details class='tree task-category' open><summary><h3>").append(escape(title))
                .append("</h3></summary><section class='taskgroup' data-state='")
                .append(state).append("' data-kind='").append(kind).append("'>")
                .append(cards);
        if (!wroteTitle) html.append("<div class='card meta'>暂无项目</div>");
        html.append("</section></details>");
    }

    private static String renderCourses(RadarSync.Result result) {
        StringBuilder html = new StringBuilder(pageStart("课程"));
        appendUpdatedAt(html, result);
        html.append("<input class='search' id='q' placeholder='搜索课程、学校或学期' oninput=\"filterCourses(this.value)\">");
        result.courses.sort((a, b) -> {
            int platformOrder = a.platform.compareTo(b.platform);
            if (platformOrder != 0) return platformOrder;
            int termOrder = b.term.compareTo(a.term);
            return termOrder != 0 ? termOrder : a.name.compareTo(b.name);
        });
        java.util.LinkedHashMap<String, java.util.LinkedHashMap<String,
                java.util.List<RadarSync.Course>>> groups = new java.util.LinkedHashMap<>();
        for (RadarSync.Course course : result.courses) {
            String major = "MOOC".equals(course.platform) ? "MOOC" : "延河 / 智园课堂";
            String group = TextUtils.isEmpty(course.term) ? "学期未标注" : course.term;
            groups.computeIfAbsent(major, key -> new java.util.LinkedHashMap<>())
                    .computeIfAbsent(group, key -> new java.util.ArrayList<>()).add(course);
        }
        for (java.util.Map.Entry<String, java.util.LinkedHashMap<String,
                java.util.List<RadarSync.Course>>> platform : groups.entrySet()) {
            html.append("<details class='tree' open><summary><h1 style='display:inline-block;font-size:22px;margin-top:28px'>")
                    .append(escape(platform.getKey())).append("</h1></summary>");
            for (java.util.Map.Entry<String, java.util.List<RadarSync.Course>> term
                    : platform.getValue().entrySet()) {
                html.append("<details class='tree term-tree' open><summary><h2 style='display:inline-block'>")
                        .append(escape(term.getKey())).append("</h2></summary>");
                for (RadarSync.Course course : term.getValue()) {
                    String searchable = (course.name + " " + course.school + " " + course.term)
                            .toLowerCase(Locale.ROOT);
                    html.append("<details class='card course tree course-tree' data-search='")
                            .append(escape(searchable)).append("'><summary>").append(escape(course.name));
                    if (!TextUtils.isEmpty(course.school)) html.append("<div class='meta'>")
                            .append(escape(course.school)).append("</div>");
                    html.append("</summary><div class='detail'>平台：").append(escape(course.platform))
                            .append("<br>学期：").append(escape(course.term));
                    if (!TextUtils.isEmpty(course.url)) html.append("<br><br><a href='")
                            .append(escape(course.url)).append("'>打开课程详情</a>");
                    html.append("</div></details>");
                }
                html.append("</details>");
            }
            html.append("</details>");
        }
        html.append("<script>function filterCourses(q){q=q.toLowerCase();document.querySelectorAll('.course').forEach(e=>e.style.display=e.dataset.search.includes(q)?'block':'none')}</script>");
        return html.append("</body></html>").toString();
    }

    private String renderCalendar(RadarSync.Result result, String accountNamespace) {
        Set<String> taskDays = new java.util.HashSet<>();
        JSONObject agenda = new JSONObject();
        JSONObject savedPriorities = new JSONObject();
        if (result != null) for (RadarSync.Task task : result.tasks) {
            if (task.due.length() >= 10) {
                String day = task.due.substring(0, 10);
                taskDays.add(day);
                JSONArray items = agenda.optJSONArray(day);
                if (items == null) { items = new JSONArray(); try { agenda.put(day, items); } catch (Exception ignored) { } }
                JSONObject item = new JSONObject();
                String key = digest(task.course + "|" + task.title + "|" + task.due)
                        .substring(0, 12);
                String savedPriority = getSharedPreferences(PROFILE_PREFS, MODE_PRIVATE)
                        .getString("task_priority_" + accountNamespace + "_" + key, "");
                if (!savedPriority.isEmpty()) try { savedPriorities.put(key, savedPriority); }
                catch (Exception ignored) { }
                try { item.put("title", task.title); item.put("course", task.course);
                    item.put("time", task.due); item.put("key", key); items.put(item); }
                catch (Exception ignored) { }
            }
        }
        StringBuilder dates = new StringBuilder("[");
        for (String date : taskDays) dates.append("'").append(date).append("',");
        dates.append("]");
        StringBuilder html = new StringBuilder(pageStart("日历"));
        appendUpdatedAt(html, result);
        html.append("<div class='monthbar'><button onclick='move(-1)'>‹</button><b id='month'></b><button onclick='goToday()'>今天</button><button onclick='move(1)'>›</button></div>"
                + "<div class='week'><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div><div class='grid' id='grid'></div><div id='agenda'></div>"
                + "<script>const tasks=new Set(").append(dates).append("),items=")
                .append(agenda.toString()).append(",savedPriorities=")
                .append(savedPriorities.toString()).append(",ns='a:")
                .append(escape(accountNamespace)).append(":',rank={red:0,yellow:1,green:2,blue:3},monthEl=document.getElementById('month'),gridEl=document.getElementById('grid'),agendaEl=document.getElementById('agenda');let view=new Date();view.setDate(1);let now=new Date(),selected=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');"
                + "function priority(x){return savedPriorities[x.key]||localStorage.getItem(ns+'urgency:'+x.key)||'blue'}function dayPriority(k){let a=items[k]||[],p='blue';a.forEach(x=>{let q=priority(x);if(rank[q]<rank[p])p=q});return p}"
                + "function showAgenda(k,scroll){let a=[...(items[k]||[])].sort((x,y)=>rank[priority(x)]-rank[priority(y)]);agendaEl.innerHTML='<h2>'+k+' 日程</h2>'+(a.length?a.map(x=>`<div class=\"card p-${priority(x)}\"><b>${x.title}</b><div class=meta>${x.course} · ${x.time}</div></div>`).join(''):'<div class=empty>当天没有任务</div>');if(scroll)agendaEl.scrollIntoView({behavior:'smooth'})}"
                + "function openDay(el,k){selected=k;document.querySelectorAll('.day').forEach(x=>x.classList.remove('selected'));el.classList.add('selected');showAgenda(k,true)}"
                + "function render(){let y=view.getFullYear(),m=view.getMonth(),n=new Date(y,m+1,0).getDate(),blank=(new Date(y,m,1).getDay()+6)%7;monthEl.textContent=y+'年 '+(m+1)+'月';gridEl.innerHTML='<span></span>'.repeat(blank);for(let d=1;d<=n;d++){let key=y+'-'+String(m+1).padStart(2,'0')+'-'+String(d).padStart(2,'0'),today=now.getFullYear()==y&&now.getMonth()==m&&now.getDate()==d;gridEl.innerHTML+=`<div class='day ${today?'today':''} ${key===selected?'selected':''}' onclick=\"openDay(this,'${key}')\">${d}${tasks.has(key)?'<i class=\"dot '+dayPriority(key)+'\"></i>':''}</div>`}}function move(n){view.setMonth(view.getMonth()+n);agendaEl.innerHTML='';render()}function goToday(){now=new Date();view=new Date(now.getFullYear(),now.getMonth(),1);selected=now.getFullYear()+'-'+String(now.getMonth()+1).padStart(2,'0')+'-'+String(now.getDate()).padStart(2,'0');render();showAgenda(selected,false)}render();showAgenda(selected,false);</script>");
        return html.append("</body></html>").toString();
    }

    private static String emptyPage(String title, String message) {
        return pageStart(title) + "<div class='empty'>" + escape(message) + "</div></body></html>";
    }

    private static void appendUpdatedAt(StringBuilder html, RadarSync.Result result) {
        if (result.savedAt <= 0) return;
        java.text.SimpleDateFormat format = new java.text.SimpleDateFormat(
                "yyyy-MM-dd HH:mm", Locale.CHINA);
        html.append("<div class='meta' style='margin:-15px 2px 18px'>数据更新于 ")
                .append(format.format(new java.util.Date(result.savedAt))).append("</div>");
    }

    private static String escape(String value) {
        if (value == null) return "";
        return value.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&#39;");
    }

    private String sanitizedPageUrl() {
        String current = webView.getUrl();
        if (current == null) {
            return "";
        }
        Uri uri = Uri.parse(current);
        return uri.buildUpon().clearQuery().fragment(null).build().toString();
    }

    @Override
    public void onBackPressed() {
        if (profilePanel.getVisibility() == View.VISIBLE) {
            leaveProfile();
        } else if (accountManagePanel.getVisibility() == View.VISIBLE) {
            leaveAccountManager();
        } else if (settingsPanel.getVisibility() == View.VISIBLE) {
            leavePlatformSettings();
        } else if (accountPanel.getVisibility() == View.VISIBLE) {
            closeDrawer();
        } else if (webView.canGoBack()) {
            webView.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        webView.destroy();
        super.onDestroy();
    }

    private static final class Validation {
        final int status;
        final boolean ok;

        Validation(int status, boolean ok) {
            this.status = status;
            this.ok = ok;
        }
    }
}
