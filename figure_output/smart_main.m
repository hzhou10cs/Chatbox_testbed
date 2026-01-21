%% SMART Main Plot: Boxplot of per-user overall SMART across benchmarks
% MATLAB R2025a
%
% Data source (per benchmark): one results_smart_sessions*.xlsx file
% Required columns (case-insensitive):
%   - user_id
%   - overall_mean_across_present_domains   (0..5)
%
% Optional columns (case-insensitive):
%   - status_code   (if exists, keep status_code==200)
%   - parse_error   (if exists, drop non-empty parse_error rows)
%   - num_domains_with_goals (if exists, keep >0)

clear; clc;

% -------------------- USER CONFIG --------------------
xlsxFiles  = { ...
    'eval_results\eval_smart_mode0\results_sessions.xlsx', ...   % Benchmark A (replace)
    'eval_results\eval_smart_mode1\results_sessions.xlsx', ...   % Benchmark B (replace)
    'eval_results\eval_smart_mode2\results_sessions.xlsx'  ...   % Benchmark C (replace)
};

benchNames = {'SSC','MSS','SA'};
nBench = numel(xlsxFiles);
% -----------------------------------------------------

% -------------------- STYLE ---------------------------
fontName      = 'Helvetica';
axFontSize    = 16;
labelFontSize = 17.6;

% Benchmark colors (A/B/C) as you specified
cBlue   = [0.0353, 0.5176, 0.8902];
cRed    = [0.9098, 0.2549, 0.0941];
cOrange = [0.9294, 0.6941, 0.1255];
colors  = [cRed; cBlue; cOrange];   % A/B/C
% -----------------------------------------------------

% -------------------- LOAD & AGGREGATE (user-level) ----------------
benchScores = cell(nBench,1);
benchUsers  = cell(nBench,1);

for b = 1:nBench
    [benchScores{b}, benchUsers{b}] = load_user_smart_scores(xlsxFiles{b});
end

% Build boxplot vectors (allow unequal #users across benchmarks)
vals = [];
grp  = [];
for b = 1:nBench
    v = benchScores{b};
    v = v(~isnan(v));                  % drop invalid users
    vals = [vals; v(:)];
    grp  = [grp;  b*ones(numel(v),1)];
end

% -------------------- PLOT ----------------------------
fig = figure('Color','w', 'Position',[100 100 500 400]);
ax  = axes(fig); hold(ax,'on');

boxplot(ax, vals, grp, ...
    'Labels', benchNames, ...
    'Symbol', '', ...
    'Whisker', 1.5, ...
    'Widths', 0.55);

% Bold boxplot lines
set(findobj(ax,'Type','Line'), 'LineWidth', 2);

% Color boxes robustly by reading their x-center
hBox = findobj(ax, 'Tag', 'Box');  % returned in reverse order
for i = 1:numel(hBox)
    xd = get(hBox(i), 'XData');
    yd = get(hBox(i), 'YData');
    xCenter = mean(xd);

    % Map to nearest benchmark index (1..nBench)
    bIdx = round(xCenter);
    bIdx = max(1, min(nBench, bIdx));

    patch('XData', xd, 'YData', yd, ...
        'FaceColor', colors(bIdx,:), 'FaceAlpha', 0.18, ...
        'EdgeColor', colors(bIdx,:), 'LineWidth', 2);
end

% Overlay per-user points with jitter (per benchmark)
jitterAmount = 0.10;
for b = 1:nBench
    y = benchScores{b};
    y = y(~isnan(y));
    x0 = b;
    xj = x0 + (rand(size(y))-0.5) * 2 * jitterAmount;
    plot(ax, xj, y, 'o', 'MarkerSize', 6, 'LineWidth', 1.5, 'Color', colors(b,:));
end

% Axes formatting
ylim(ax, [3 5]);
yticks(ax, 3:0.5:5);

ylabel(ax, 'Overall SMART Score (0–5)', ...
    'FontName', fontName, 'FontSize', labelFontSize, 'FontWeight', 'bold');

set(ax, 'FontName', fontName, 'FontSize', axFontSize, ...
    'FontWeight', 'bold', 'LineWidth', 1);

grid(ax, 'on');
box(ax, 'off');
xlim(ax, [0.5, nBench+0.5]);

% Optional export
% exportgraphics(fig, 'smart_boxplot.png', 'Resolution', 300);
% exportgraphics(fig, 'smart_boxplot.pdf', 'ContentType', 'vector');

%% -------------------- LOCAL FUNCTION --------------------
function [userScore, userList] = load_user_smart_scores(xlsxPath)
%LOAD_USER_SMART_SCORES Compute per-user overall SMART score from one results_smart_sessions.xlsx
% User-level aggregation:
%   userScore(u) = mean(overall_mean_across_present_domains across sessions)

    assert(isfile(xlsxPath), 'Excel file not found: %s', xlsxPath);

    T = readtable(xlsxPath, 'VariableNamingRule','preserve');
    vars = string(T.Properties.VariableNames);
    varsLower = lower(vars);

    % Required columns (case-insensitive match)
    iUser = find(varsLower == "user_id", 1);
    iOv   = find(varsLower == "overall_mean_across_present_domains", 1);

    assert(~isempty(iUser), 'Missing column "user_id" in %s', xlsxPath);
    assert(~isempty(iOv),   'Missing column "overall_mean_across_present_domains" in %s', xlsxPath);

    user = string(T.(vars(iUser)));
    ov   = double(T.(vars(iOv)));

    % Base validity
    valid = ~ismissing(user) & ~ismissing(ov) & isfinite(ov);

    % Optional: keep only successful rows if status_code exists
    iStatus = find(varsLower == "status_code", 1);
    if ~isempty(iStatus)
        sc = T.(vars(iStatus));
        valid = valid & ~ismissing(sc) & (sc == 200);
    end

    % Optional: drop parse_error rows if parse_error exists
    iParse = find(varsLower == "parse_error", 1);
    if ~isempty(iParse)
        pe = T.(vars(iParse));
        okParse = true(height(T),1);

        if iscell(pe)
            okParse = cellfun(@(x) isempty(x) || (ischar(x) && isempty(strtrim(x))) || (isstring(x) && strlength(x)==0), pe);
        elseif isstring(pe)
            okParse = ismissing(pe) | (strlength(pe)==0);
        end

        valid = valid & okParse;
    end

    % Optional: require num_domains_with_goals > 0 if exists
    iND = find(varsLower == "num_domains_with_goals", 1);
    if ~isempty(iND)
        nd = double(T.(vars(iND)));
        valid = valid & ~ismissing(nd) & isfinite(nd) & (nd > 0);
    end

    user = lower(strtrim(user(valid)));
    ov   = ov(valid);

    % Clamp to [0,5] (safety)
    ov = min(5, max(0, ov));

    % Group by user and average across sessions
    [G, userList] = findgroups(user);
    userScore = splitapply(@(x) mean(x,'omitnan'), ov, G);

    userScore = userScore(:);
    userList  = string(userList(:));
end
