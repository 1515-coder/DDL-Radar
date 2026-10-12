package cn.ddlradar.mobile;

import android.text.TextUtils;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/** Small, bounded API synchronizer. It never crawls individual course pages. */
final class RadarSync {
    private static final String MOOC_ROOT = "https://www.icourse163.org";
    private static final String YANHE_ROOT = "https://aita.yanhekt.cn";
    private static final String ZHIYUAN_ROOT = "https://zy-eclass.bit.edu.cn";

    private RadarSync() {}

    static Result run(String moocCookie, String moocCsrf, String yanheCookie,
                      String zhiyuanCookie, String userAgent) {
        Result result = new Result();
        if (!TextUtils.isEmpty(moocCookie)) result.attemptedPlatforms.add("MOOC");
        if (!TextUtils.isEmpty(moocCookie) && !TextUtils.isEmpty(moocCsrf)) {
            try {
                for (int page = 1; page <= 20; page++) {
                JSONObject root = request("POST", MOOC_ROOT
                                + "/web/j/learnerCourseRpcBean.getMyLearnedCoursePanelList.rpc?csrfKey="
                                + URLEncoder.encode(moocCsrf, "UTF-8"), moocCookie, userAgent,
                        "type=30&p=" + page + "&psize=100&courseType=1");
                JSONArray courses = root.optJSONObject("result") == null ? null
                        : root.optJSONObject("result").optJSONArray("result");
                if (courses != null) {
                    for (int i = 0; i < courses.length(); i++) {
                        JSONObject raw = courses.optJSONObject(i);
                        if (raw == null) continue;
                        JSONObject term = raw.optJSONObject("termPanel");
                        JSONObject school = raw.optJSONObject("schoolPanel");
                        Course course = new Course("MOOC", raw.optString("name", "未命名课程"),
                                term == null ? "" : termLabel(term),
                                school == null ? "" : school.optString("name"),
                                term == null ? 0 : term.optLong("id"),
                                MOOC_ROOT + "/learn/"
                                        + (school == null ? "" : school.optString("shortName"))
                                        + "-" + raw.optLong("id") + "?tid="
                                        + (term == null ? 0 : term.optLong("id"))
                                        + "#/learn/content", "");
                        result.courses.add(course);
                        if (course.termId > 0 && isActive(term)) {
                            try {
                                JSONObject detail = request("POST", MOOC_ROOT
                                                + "/web/j/courseBean.getLastLearnedMocTermDto.rpc?csrfKey="
                                                + URLEncoder.encode(moocCsrf, "UTF-8"),
                                        moocCookie, userAgent, "termId=" + course.termId);
                                JSONObject payload = detail.optJSONObject("result");
                                parseMoocTasks(payload == null ? detail : payload,
                                        course.name, result.tasks, new HashSet<>(), null, "其他");
                            } catch (Exception error) {
                                result.errors.add("MOOC「" + course.name + "」：" + concise(error));
                            }
                        }
                    }
                }
                if (courses == null || courses.length() < 100) break;
                }
                result.successfulPlatforms.add("MOOC");
            } catch (Exception error) {
                if (isAuthenticationFailure(error)) result.invalidPlatforms.add("MOOC");
                result.errors.add("MOOC：" + concise(error));
            }
        } else if (!TextUtils.isEmpty(moocCookie)) {
            result.errors.add("MOOC：请打开一次 MOOC 课程页后再同步");
        }

        if (!TextUtils.isEmpty(yanheCookie)) {
            result.attemptedPlatforms.add("YANHE");
            try {
                int page = 1;
                int total = Integer.MAX_VALUE;
                int loaded = 0;
                while (loaded < total && page <= 50) {
                    JSONObject root = request("GET", YANHE_ROOT
                            + "/personal/courseapi/vlabpassportapi/v1/account-profile/course"
                            + "?nowpage=" + page + "&per-page=100", yanheCookie, userAgent, null);
                    JSONObject data = root.optJSONObject("params") == null ? null
                            : root.optJSONObject("params").optJSONObject("result");
                    JSONArray courses = data == null ? null : data.optJSONArray("data");
                    if (courses == null) throw new IllegalStateException("课程接口未返回数据");
                    total = data.optInt("total", courses.length());
                    for (int i = 0; i < courses.length(); i++) {
                        JSONObject raw = courses.optJSONObject(i);
                        if (raw == null) continue;
                        String zhiyuanId = "";
                        try {
                            Object information = raw.opt("information");
                            JSONObject info = information instanceof JSONObject
                                    ? (JSONObject) information : new JSONObject(String.valueOf(information));
                            zhiyuanId = raw.optString("zhiyuan_id", info.optString("zhiyuan_id"));
                        } catch (Exception ignored) { }
                        result.courses.add(new Course("延河课堂", raw.optString("Title", "未命名课程"),
                                raw.optString("TermName"), raw.optString("KkxyName"), 0,
                                TextUtils.isEmpty(zhiyuanId) ? ""
                                        : ZHIYUAN_ROOT + "/course/" + zhiyuanId + "/content",
                                zhiyuanId));
                    }
                    loaded += courses.length();
                    if (courses.length() == 0 || courses.length() < 100) break;
                    page++;
                }
                result.successfulPlatforms.add("YANHE");
            } catch (Exception error) {
                if (isAuthenticationFailure(error)) result.invalidPlatforms.add("YANHE");
                result.errors.add("延河课堂：" + concise(error));
            }
        }

        if (!TextUtils.isEmpty(zhiyuanCookie)) {
            result.attemptedPlatforms.add("ZHIYUAN");
            try {
                JSONObject root = request("GET", ZHIYUAN_ROOT
                        + "/api/todos?no-intercept=true", zhiyuanCookie, userAgent, null);
                JSONArray todos = firstArray(root, "todo_list", "todos", "data", "result");
                if (todos == null) throw new IllegalStateException("待办接口未返回列表");
                for (int i = 0; i < todos.length(); i++) {
                    JSONObject raw = todos.optJSONObject(i);
                    if (raw == null) continue;
                    String type = raw.optString("type").toLowerCase(Locale.ROOT);
                    if (!(type.contains("homework") || type.contains("exam")
                            || type.contains("questionnaire") || type.contains("quiz"))) continue;
                    result.tasks.add(new Task("智园课堂", raw.optString("course_name",
                                    raw.optString("course", "智园课堂")),
                            raw.optString("title", raw.optString("name", "未命名任务")),
                            typeName(type), localTime(firstText(
                                    raw, "end_time", "deadline", "closed_time")), false,
                            firstText(raw, "description", "content", "summary")));
                }
                fetchZhiyuanHistory(result, zhiyuanCookie, userAgent);
                result.successfulPlatforms.add("ZHIYUAN");
            } catch (Exception error) {
                if (isAuthenticationFailure(error)) result.invalidPlatforms.add("ZHIYUAN");
                result.errors.add("智园课堂：" + concise(error));
            }
        }
        return result;
    }

    private static JSONObject request(String method, String address, String cookie,
                                      String userAgent, String body) throws Exception {
        if (Thread.currentThread().isInterrupted()) throw new InterruptedException("同步已取消");
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(15_000);
        connection.setReadTimeout(25_000);
        connection.setRequestMethod(method);
        connection.setRequestProperty("Accept", "application/json,text/plain,*/*");
        connection.setRequestProperty("Cookie", cookie);
        connection.setRequestProperty("User-Agent", userAgent);
        connection.setRequestProperty("Referer", address.startsWith(MOOC_ROOT)
                ? MOOC_ROOT + "/home.htm" : address);
        if (body != null) {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
            connection.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(bytes); }
        }
        int status = connection.getResponseCode();
        InputStream stream = status >= 400 ? connection.getErrorStream() : connection.getInputStream();
        StringBuilder text = new StringBuilder();
        if (stream != null) {
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                    stream, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null && text.length() < 2_000_000) {
                    text.append(line);
                }
            }
        }
        connection.disconnect();
        if (status == 401 || status == 403) {
            throw new IllegalStateException("AUTH_REQUIRED HTTP " + status);
        }
        if (status < 200 || status >= 300) throw new IllegalStateException("HTTP " + status);
        if (text.length() == 0) throw new IllegalStateException("服务器返回空内容");
        String lower = text.toString().toLowerCase(Locale.ROOT);
        if (lower.startsWith("<!doctype html") || lower.startsWith("<html")) {
            if (lower.contains("login") || lower.contains("password")
                    || lower.contains("统一身份认证") || lower.contains("forcelogin")
                    || lower.contains("cas/login")) {
                throw new IllegalStateException("AUTH_REQUIRED 登录状态已失效");
            }
        }
        return new JSONObject(text.toString());
    }

    private static boolean isAuthenticationFailure(Exception error) {
        String message = error.getMessage() == null ? "" : error.getMessage();
        return message.contains("AUTH_REQUIRED") || message.contains("HTTP 401");
    }

    private static JSONArray firstArray(JSONObject root, String... keys) {
        for (String key : keys) {
            JSONArray direct = root.optJSONArray(key);
            if (direct != null) return direct;
            JSONObject object = root.optJSONObject(key);
            if (object != null) {
                JSONArray nested = firstArray(object, "todo_list", "todos", "items", "list", "data");
                if (nested != null) return nested;
            }
        }
        return null;
    }

    private static String firstText(JSONObject value, String... keys) {
        for (String key : keys) if (value.has(key) && !value.isNull(key)) return value.optString(key);
        return "";
    }

    private static String termLabel(JSONObject term) {
        long start = term.optLong("startTime");
        long end = term.optLong("endTime");
        if (start <= 0 || end <= 0) return "";
        java.text.SimpleDateFormat format = new java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.CHINA);
        return format.format(new java.util.Date(start)) + " — " + format.format(new java.util.Date(end));
    }

    private static boolean isActive(JSONObject term) {
        if (term == null) return false;
        long now = System.currentTimeMillis();
        long start = term.optLong("startTime");
        long end = term.optLong("endTime");
        return start > 0 && end > 0 && start <= now && now <= end;
    }

    private static void parseMoocTasks(Object value, String course, List<Task> output,
                                       Set<String> seen, String parentName,
                                       String inheritedType) {
        if (value instanceof JSONArray) {
            JSONArray values = (JSONArray) value;
            for (int i = 0; i < values.length(); i++) {
                parseMoocTasks(values.opt(i), course, output, seen, parentName, inheritedType);
            }
            return;
        }
        if (!(value instanceof JSONObject)) return;
        JSONObject object = (JSONObject) value;
        String ownName = object.optString("name", parentName == null ? "未命名任务" : parentName);
        long deadline = object.optLong("deadline");
        if (deadline > 0) {
            String identity = object.optString("id") + ":" + deadline;
            boolean completed = object.optInt("usedTryCount") > 0
                    || (object.has("userScore") && !object.isNull("userScore"));
            if (seen.add(identity)) {
                output.add(new Task("MOOC", course, ownName, inheritedType, localMillis(deadline),
                        completed, firstText(object, "description", "content", "remark")));
            }
        }
        java.util.Iterator<String> keys = object.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            String nextType = inheritedType;
            if ("homeworks".equals(key)) nextType = "作业";
            else if ("quizs".equals(key) || "quiz".equals(key)) nextType = "测验";
            else if ("exams".equals(key) || "exam".equals(key)) nextType = "考试";
            parseMoocTasks(object.opt(key), course, output, seen, ownName, nextType);
        }
    }

    private static String typeName(String type) {
        if (type.contains("homework")) return "作业";
        if (type.contains("exam")) return "测验";
        return "问卷";
    }

    private static String localTime(String value) {
        if (TextUtils.isEmpty(value)) return "";
        try {
            Instant instant = OffsetDateTime.parse(value).toInstant();
            return DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")
                    .withLocale(Locale.CHINA)
                    .withZone(ZoneId.of("Asia/Shanghai"))
                    .format(instant);
        } catch (Exception ignored) {
            return value;
        }
    }

    private static String localMillis(long value) {
        return DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")
                .withLocale(Locale.CHINA)
                .withZone(ZoneId.of("Asia/Shanghai"))
                .format(Instant.ofEpochMilli(value));
    }

    private static String concise(Exception error) {
        String message = error.getMessage();
        return TextUtils.isEmpty(message) ? error.getClass().getSimpleName()
                : message.replace("AUTH_REQUIRED ", "");
    }

    private static void fetchZhiyuanHistory(Result result, String cookie, String userAgent) {
        String[][] definitions = {
                {"homework-activities", "homework_activities", "作业"},
                {"exam-list", "exams", "测验"},
                {"questionnaire-list", "questionnaires", "问卷"}
        };
        Set<String> seen = new HashSet<>();
        for (Task task : result.tasks) seen.add(task.course + "|" + task.title + "|" + task.due);
        LocalDate today = LocalDate.now(ZoneId.of("Asia/Shanghai"));
        String expectedTerm = today.getMonthValue() >= 8
                ? today.getYear() + "-" + (today.getYear() + 1) + "-1"
                : today.getMonthValue() <= 2
                ? (today.getYear() - 1) + "-" + today.getYear() + "-1"
                : (today.getYear() - 1) + "-" + today.getYear() + "-2";
        String newestTerm = "";
        for (Course course : result.courses) {
            if (!TextUtils.isEmpty(course.remoteId) && course.term.compareTo(newestTerm) > 0) {
                newestTerm = course.term;
            }
        }
        boolean expectedExists = false;
        for (Course course : result.courses) {
            if (expectedTerm.equals(course.term) && !TextUtils.isEmpty(course.remoteId)) {
                expectedExists = true;
                break;
            }
        }
        String selectedTerm = expectedExists ? expectedTerm : newestTerm;
        int reportedFailures = 0;
        outer:
        for (Course course : result.courses) {
            if (TextUtils.isEmpty(course.remoteId) || !course.term.equals(selectedTerm)) continue;
            for (String[] definition : definitions) {
                try {
                    String conditions = URLEncoder.encode(
                            "{\"itemsSortBy\":{\"predicate\":\"module\",\"reverse\":false}}",
                            "UTF-8");
                    for (int page = 1; page <= 20; page++) {
                        JSONObject payload = request("GET", ZHIYUAN_ROOT + "/api/courses/"
                                        + course.remoteId + "/" + definition[0]
                                        + "?conditions=" + conditions + "&page=" + page
                                        + "&page_size=100&reloadPage=true",
                                cookie, userAgent, null);
                        JSONArray items = payload.optJSONArray(definition[1]);
                        if (items == null || items.length() == 0) break;
                        for (int i = 0; i < items.length(); i++) {
                            JSONObject raw = items.optJSONObject(i);
                            if (raw == null) continue;
                            String due = localTime(firstText(raw, "deadline", "end_time", "closed_time"));
                            if (TextUtils.isEmpty(due)) continue;
                            String title = firstText(raw, "title", "name");
                            String identity = course.name + "|" + title + "|" + due;
                            if (!seen.add(identity)) continue;
                            boolean completed = raw.optBoolean("submitted")
                                    || raw.optInt("user_submit_count") > 0
                                    || (raw.has("final_score") && !raw.isNull("final_score"))
                                    || (raw.has("user_submission") && !raw.isNull("user_submission"));
                            result.tasks.add(new Task("智园课堂", course.name,
                                    TextUtils.isEmpty(title) ? "未命名任务" : title,
                                    definition[2], due, completed,
                                    firstText(raw, "description", "content", "instruction", "remark")));
                        }
                        if (items.length() < 100) break;
                    }
                } catch (Exception error) {
                    String message = concise(error);
                    if (message.contains("Unable to resolve host")
                            || message.contains("No address associated")) {
                        result.errors.add("智园「" + course.name + "」" + definition[2]
                                + "：网络无法连接，后续课程未继续补查");
                        break outer;
                    }
                    if (!message.contains("HTTP 403") && reportedFailures++ < 12) {
                        result.errors.add("智园「" + course.name + "」" + definition[2]
                                + "：" + message);
                    }
                }
            }
        }
        // 403 is expected for courses that do not publish a particular activity type.
        // The global todo feed remains valid, so do not present this as an import failure.
        if (reportedFailures > 12) result.errors.add("智园历史任务：另有 "
                + (reportedFailures - 12) + " 个具体项目读取失败");
    }

    static final class Result {
        final List<Course> courses = new ArrayList<>();
        final List<Task> tasks = new ArrayList<>();
        final List<String> errors = new ArrayList<>();
        final Set<String> invalidPlatforms = new HashSet<>();
        final Set<String> attemptedPlatforms = new HashSet<>();
        final Set<String> successfulPlatforms = new HashSet<>();
        long savedAt;
    }

    static final class Course {
        final String platform, name, term, school, url, remoteId;
        final long termId;
        Course(String platform, String name, String term, String school, long termId,
               String url, String remoteId) {
            this.platform = platform; this.name = name; this.term = term; this.school = school;
            this.termId = termId; this.url = url; this.remoteId = remoteId;
        }
    }

    static final class Task {
        final String platform, course, title, type, due, details;
        final boolean completed;
        Task(String platform, String course, String title, String type, String due,
             boolean completed, String details) {
            this.platform = platform; this.course = course; this.title = title;
            this.type = type; this.due = due;
            this.completed = completed; this.details = details;
        }
    }
}
